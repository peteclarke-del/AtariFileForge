from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, jsonify, request, send_file, send_from_directory

from ..download_archive import build_download_archive, prepared_download
from ..disk_service import DiskError, DiskService
from ..image_opening import open_image_upload
from ..hardware_profiles import hardware_catalogue, normalise_hardware_profile
from ..operations import OperationRegistry
from ..platform_contract import PlatformRuntime
from ..version import application_version
from .common import apply_partition, payload
from .effects import image_mutation, request_effect


def create_images_blueprint(
    service: DiskService,
    static_dir: Path,
    operations: OperationRegistry,
    runtime: PlatformRuntime | None = None,
) -> Blueprint:
    runtime = runtime or PlatformRuntime()
    blueprint = Blueprint("images", __name__)

    @blueprint.get("/")
    def index():
        return send_from_directory(static_dir, "index.html")

    @blueprint.get("/api/health")
    def health():
        return jsonify(
            status="ok",
            engine="atarinut",
            version=application_version(),
            platform=runtime.public_contract(),
        )

    @blueprint.get("/api/hardware-profiles")
    def list_hardware_profiles():
        return jsonify(hardware_catalogue())

    @blueprint.post("/api/images")
    @request_effect("lifecycle", "opening an image session")
    def open_image():
        image = request.files.get("image")
        if not image or not image.filename:
            raise DiskError("Choose a media image to open.")
        try:
            rom_component_names = json.loads(
                request.form.get("romComponentNames", "[]")
            )
        except json.JSONDecodeError as exc:
            raise DiskError("The ROM component list is invalid.") from exc
        if not isinstance(rom_component_names, list):
            raise DiskError("The ROM component list is invalid.")
        session = open_image_upload(
            service,
            image,
            target_hardware=request.form.get("targetHardware", "auto"),
            rom_options={
                "layout": request.form.get("romLayout", "linear"),
                "platform": request.form.get("romPlatform", "tos"),
                "componentNames": rom_component_names,
            },
            force_kind=request.form.get("forceKind") or None,
        )
        return jsonify(image=service.summary(session))

    @blueprint.post("/api/images/create")
    @request_effect("lifecycle", "creating an image session")
    def create_image():
        data = payload()
        # Each shape of media takes its own options, and the pane sends the
        # group that belongs to the format it asked for. They are merged into
        # one object here so the service has a single place to read them.
        options: dict = {}
        for group in ("rom", "hardDisk"):
            if isinstance(data.get(group), dict):
                options.update(data[group])
        if data.get("bootable") is not None:
            options["bootable"] = bool(data["bootable"])
        session = service.create_blank(
            data.get("format", "ds-720k"),
            data.get("title", "BLANK"),
            data.get("capacity"),
            data.get("targetHardware", "auto"),
            options=options or None,
        )
        return jsonify(image=service.summary(session))

    @blueprint.get("/api/images/<image_id>")
    def image_summary(image_id):
        return jsonify(image=service.summary(service.get(image_id)))

    @blueprint.get("/api/images/<image_id>/partitions")
    def image_partitions(image_id):
        """List the partitions a hard disk's own table declares.

        Each row is presented as a folder so the pane opens into it exactly as
        it opens a directory, and carries the drive letter TOS assigns it, the
        three-letter identifier or MBR type code, its extent and whether the
        machine boots from it.
        """
        session = service.get(image_id)
        partitions = [
            {
                "partition": index,
                "name": str(item.get("device") or item.get("name") or f"Partition {index}"),
                "type": "partition",
                "label": str(item.get("label") or ""),
                # The three-letter identifier AHDI writes, or the two-digit
                # MBR type code, is what a person recognises the partition by.
                "identifier": str(item.get("id") or ""),
                "id": str(item.get("id") or ""),
                "typeCode": item.get("typeCode"),
                "format": str(item.get("format") or ""),
                # AHDI boots the first partition whose flag is set, so the
                # only priority there is order.
                "bootPriority": index if item.get("bootable") else None,
                "length": int(item.get("sizeBytes") or 0),
                "startSector": int(item.get("startSector") or 0),
                "sizeSectors": int(item.get("sizeSectors") or 0),
                "bootable": bool(item.get("bootable")),
                "byteSwapped": bool(item.get("byteSwapped")),
                "gemdos": bool(item.get("gemdos")),
            }
            for index, item in enumerate(service.list_partitions(session))
        ]
        return jsonify(image=service.summary(session), partitions=partitions)

    @blueprint.get("/api/images/<image_id>/partition-table")
    def image_partition_table(image_id):
        """Return the complete decoded partition table for inspection.

        The report names the scheme that was found, how many sectors the
        table claims the drive holds, whether the image is byte-swapped, and
        every partition the table reaches, chained tables included.
        """
        return jsonify(partitionTable=service.partition_table(service.get(image_id)))

    @blueprint.patch("/api/images/<image_id>")
    @image_mutation("renaming the image")
    def rename_image(image_id):
        data = payload()
        session = service.get(image_id)
        service.rename_session(session, data.get("name", ""))
        return jsonify(image=service.summary(session))

    @blueprint.patch("/api/images/<image_id>/rom-layout")
    @image_mutation("changing the ROM layout")
    def configure_rom_layout(image_id):
        data = payload()
        session = service.get(image_id)
        service.configure_rom(
            session,
            bank_size=int(data.get("bankSize", session.rom_bank_size)),
            erase_byte=int(str(data.get("eraseByte", session.rom_erase_byte)), 0),
            platform=str(data.get("platform") or session.rom_platform),
            layout=str(data.get("layout") or session.rom_layout),
        )
        return jsonify(image=service.summary(session))

    @blueprint.patch("/api/images/<image_id>/hardware-profile")
    @image_mutation("changing the hardware profile")
    def set_hardware_profile(image_id):
        data = payload()
        session = service.get(image_id)
        allowed = {
            "name", "machine", "filingSystem", "handlerBuild", "accelerated",
            "page", "menuType", "notes", "targetHardware", "catalogMachine",
            "emulator", "debugger", "emulatorRam", "emulatorBoot", "addons",
        }
        profile = {
            key: value
            for key, value in data.items()
            if key in allowed and isinstance(value, (str, bool, int, float, list))
        }
        try:
            profile = normalise_hardware_profile(profile)
        except ValueError as exc:
            raise DiskError(str(exc)) from exc
        for key in ("emulator", "debugger", "emulatorRam", "emulatorBoot"):
            if key in profile:
                profile[key] = str(profile[key]).strip()[:2048]
        session.hardware_profile = profile
        if data.get("targetHardware"):
            session.target_hardware = service._target_hardware(str(data["targetHardware"]))
        service._persist_session(session)
        return jsonify(image=service.summary(session))

    @blueprint.get("/api/images/<image_id>/checkpoints")
    def image_checkpoints(image_id):
        session = service.get(image_id)
        return jsonify(
            image=service.summary(session),
            checkpoints=service.list_checkpoints(session),
        )

    @blueprint.post("/api/images/<image_id>/checkpoints")
    @request_effect("lifecycle", "creating a named checkpoint")
    def create_image_checkpoint(image_id):
        data = payload()
        session = service.get(image_id)
        checkpoint = service.create_checkpoint(session, data.get("name", ""))
        return jsonify(
            image=service.summary(session),
            checkpoint=checkpoint,
            checkpoints=service.list_checkpoints(session),
        )

    @blueprint.post("/api/images/<image_id>/checkpoints/<checkpoint_id>/restore")
    @request_effect("lifecycle", "restoring an explicitly managed checkpoint")
    def restore_image_checkpoint(image_id, checkpoint_id):
        session = service.get(image_id)
        service.begin_automatic_checkpoint(session, "restoring a named checkpoint")
        checkpoint = service.restore_checkpoint(session, checkpoint_id)
        return jsonify(
            image=service.summary(session),
            checkpoint=checkpoint,
            checkpoints=service.list_checkpoints(session),
        )

    @blueprint.delete("/api/images/<image_id>/checkpoints/<checkpoint_id>")
    @request_effect("lifecycle", "deleting checkpoint metadata")
    def delete_image_checkpoint(image_id, checkpoint_id):
        session = service.get(image_id)
        service.delete_checkpoint(session, checkpoint_id)
        return jsonify(
            image=service.summary(session),
            checkpoints=service.list_checkpoints(session),
        )

    @blueprint.post("/api/images/<image_id>/undo")
    @request_effect("lifecycle", "restoring the automatic undo checkpoint")
    def undo_image_change(image_id):
        session = service.get(image_id)
        checkpoint = service.undo_last_change(session)
        return jsonify(
            image=service.summary(session),
            checkpoint=checkpoint,
            checkpoints=service.list_checkpoints(session),
        )

    @blueprint.get("/api/images/recoverable")
    def recoverable_images():
        return jsonify(images=service.recoverable_sessions())

    @blueprint.delete("/api/images/recoverable")
    @request_effect("lifecycle", "clearing owned recovery sessions")
    def clear_recoverable_images():
        data = request.get_json(silent=True) or {}
        image_ids = data.get("imageIds")
        if image_ids is not None and not isinstance(image_ids, list):
            raise DiskError("Choose the sessions to clear.")
        removed = service.clear_recoverable_sessions(image_ids)
        return jsonify(removed=removed)

    @blueprint.delete("/api/images/<image_id>")
    @request_effect("lifecycle", "discarding an image session")
    def discard_image(image_id):
        service.discard_session(service.get(image_id))
        return ("", 204)

    @blueprint.get("/api/images/<image_id>/download")
    def download_image(image_id):
        session = service.get(image_id)
        archive_path, archive_name = prepared_download(session)
        return send_file(
            archive_path,
            mimetype="application/zip",
            as_attachment=True,
            download_name=archive_name,
            conditional=True,
        )

    @blueprint.post("/api/images/<image_id>/download/prepare")
    @image_mutation("finalising the image for download")
    def prepare_image_download(image_id):
        data = payload()
        operation_id = data.get("operationId")
        session = service.get(image_id)
        with operations.tracked(
            operation_id,
            "Preparing image download",
            "The complete ZIP is ready to download",
        ) as progress:
            with session.lock:
                build_download_archive(service, session, progress)
                service.mark_saved(session)
            return jsonify(image=service.summary(session), ready=True)

    @blueprint.post("/api/images/<image_id>/convert")
    @request_effect("lifecycle", "creating a converted image session")
    def convert_image(image_id):
        """Rebuild the disk an MSA, DIM or Pasti container describes."""
        data = payload()
        converted, tracks = service.convert_container(
            service.get(image_id),
            data.get("format", "st"),
        )
        return jsonify(image=service.summary(converted), files=tracks)

    @blueprint.get("/api/images/<image_id>/export/formats")
    def image_export_formats(image_id):
        return jsonify(formats=service.export_formats(service.get(image_id)))

    @blueprint.get("/api/images/<image_id>/export")
    def export_image(image_id):
        session = service.get(image_id)
        target_format = request.args.get("format", "native")
        output, download_name = service.export_image(session, target_format)
        return send_file(
            output,
            mimetype="application/octet-stream",
            as_attachment=True,
            download_name=download_name,
            conditional=False,
        )

    @blueprint.post("/api/images/<image_id>/compact")
    @image_mutation("compacting the filesystem")
    def compact(image_id):
        data = payload()
        session = service.get(image_id)
        apply_partition(service, session, data.get("partition"))
        service.compact(session)
        return jsonify(
            image=service.summary(session),
            message="Free space compacted successfully",
        )

    return blueprint
