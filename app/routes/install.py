"""Routes for turning a floppy into something a hard drive can run.

Three of the four install modes reach an image from here and each declares
what it does to one. Staging, installing a staged title, copying in a single
program, preparing a drive and putting a title on the desktop all write into a
volume and are declared as mutations, which is what gets them an undo
checkpoint before they run. Staging is a mutation because it writes onto the
drive being built rather than into a directory on this machine, which is what
lets the install be finished in Hatari or on the real hardware. The fourth
mode, running the title's own installer, starts an emulator and changes
nothing this application owns, so it lives with the other emulator routes.
"""

from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from ..disk_service import DiskError, DiskService
from ..desktop_replacement import (
    NO_DESKTOP,
    describe_desktops,
    recommended_desktop,
)
from ..drive_preparation import (
    DEFAULT_FOLDERS,
    DRIVERLESS,
    describe_drivers,
)
from ..install_service import (
    DEFAULT_INSTALL_PARENT,
    DEFAULT_STAGING_PARENT,
)
from ..operations import OperationRegistry
from .common import apply_partition, payload
from .effects import image_mutation, request_effect


def create_install_blueprint(service: DiskService, operations: OperationRegistry) -> Blueprint:
    blueprint = Blueprint("install", __name__)

    # ------------------------------------------------------------------
    # Staging
    # ------------------------------------------------------------------

    @blueprint.get("/api/images/<image_id>/install/staged")
    def list_staged(image_id):
        """What is waiting on this drive.

        Staging writes onto the target volume, so the list is a property of an
        image and is read back off it. A drive built elsewhere still reports
        what is sitting in its staging folder.
        """
        session = service.get(image_id)
        apply_partition(service, session, request.args.get("partition"))
        parent = str(request.args.get("parent") or "")
        return jsonify(
            titles=service.staged_titles(session, parent=parent),
            root=service.staging_parent(parent),
            defaultParent=DEFAULT_STAGING_PARENT,
        )

    @blueprint.post("/api/images/<image_id>/install/stage")
    @image_mutation("staging a disk onto a drive")
    def stage(image_id):
        """Extract one disk into a folder on the drive it is destined for."""
        data = payload()
        session = service.get(image_id)
        apply_partition(service, session, data.get("partition"))
        source = service.get(data["sourceImage"])
        apply_partition(service, source, data.get("sourcePartition"))
        title = str(data.get("title") or "").strip()
        with operations.tracked(
            data.get("operationId"),
            f"Staging {title or source.name}",
            "Disk staged",
        ) as progress:
            staged = service.stage_disk(
                source,
                session,
                title or source.name,
                parent=str(data.get("stagingParent") or ""),
                disk_label=str(data.get("diskLabel") or "").strip() or None,
                progress=progress,
            )
        return jsonify(image=service.summary(session), staged=staged)

    @blueprint.post("/api/images/<image_id>/install/staged/discard")
    @image_mutation("discarding a staged title")
    def discard_staged(image_id):
        data = payload()
        session = service.get(image_id)
        apply_partition(service, session, data.get("partition"))
        parent = str(data.get("stagingParent") or "")
        service.discard_staged_title(session, str(data["name"]), parent=parent)
        return jsonify(
            image=service.summary(session),
            titles=service.staged_titles(session, parent=parent),
        )

    @blueprint.post("/api/images/<image_id>/install/staged")
    @image_mutation("installing a staged title")
    def install_staged(image_id):
        data = payload()
        session = service.get(image_id)
        apply_partition(service, session, data.get("partition"))
        with operations.tracked(
            data.get("operationId"),
            "Installing a staged title",
            "Staged title installed",
        ) as progress:
            result = service.install_staged_title(
                session,
                str(data["name"]),
                parent=str(data.get("parent", DEFAULT_INSTALL_PARENT)),
                staging=str(data.get("stagingParent") or ""),
                folder=str(data.get("folder") or "") or None,
                progress=progress,
            )
        return jsonify(image=service.summary(session), **result)

    # ------------------------------------------------------------------
    # One program on its own
    # ------------------------------------------------------------------

    @blueprint.post("/api/images/<image_id>/install/program")
    @image_mutation("copying a program onto a drive")
    def install_program(image_id):
        """Copy one program off a disk into a folder on this drive."""
        data = payload()
        session = service.get(image_id)
        apply_partition(service, session, data.get("partition"))
        source = service.get(str(data["sourceImage"]))
        apply_partition(service, source, data.get("sourcePartition"))
        result = service.install_program(
            source,
            session,
            str(data.get("path") or ""),
            parent=str(data.get("parent", DEFAULT_INSTALL_PARENT)),
            name=str(data.get("name") or ""),
        )
        return jsonify(image=service.summary(session), program=result)

    # ------------------------------------------------------------------
    # Preparing the drive itself
    # ------------------------------------------------------------------

    @blueprint.get("/api/install/drivers")
    def drivers():
        """The driver choices, so the interface can explain what it wants."""
        return jsonify(
            drivers=describe_drivers(),
            folders=list(DEFAULT_FOLDERS),
            default=DRIVERLESS,
        )

    @blueprint.get("/api/images/<image_id>/install/driver")
    def driver_state(image_id):
        """What this drive has been prepared with, read off the drive itself."""
        session = service.get(image_id)
        apply_partition(service, session, request.args.get("partition"))
        state = service.drive_preparation(session)
        state["available"] = service.available_drivers(
            _chosen_folder(request.args.get("folder"))
        )
        return jsonify(driver=state["driver"], preparation=state)

    @blueprint.post("/api/images/<image_id>/install/driver")
    @image_mutation("preparing a drive to be booted")
    def prepare_driver(image_id):
        """Prepare this drive: a driver where one is wanted, and a desktop.

        A driver whose licence allows it is downloaded when there is no copy
        here. HDDRIVER and the PP driver are sold by their authors and are
        installed from the operator's own copy or not at all. That decision is
        made against the catalogue rather than against this request.
        """
        data = payload()
        session = service.get(image_id)
        apply_partition(service, session, data.get("partition"))
        # Another open drive the same driver prepared, whose loaders are
        # copied. It is looked up like any image, so it has to be the
        # operator's own session.
        loader_image = str(data.get("loaderImage") or "").strip()
        loader_from = service.get(loader_image) if loader_image else None
        with operations.tracked(
            data.get("operationId"),
            "Preparing the drive",
            "Drive prepared",
        ) as progress:
            result = service.prepare_drive(
                session,
                driver=str(data.get("driver") or DRIVERLESS),
                loader_from=loader_from,
                create_folders=data.get("createFolders", True) is not False,
                directories=_chosen_folder(data.get("folder")),
                download=data.get("download", True) is not False,
                desktop=data.get("desktop", True) is not False,
                progress=progress,
            )
        # Keeping a copy is what lets the next drive be prepared without this
        # one open. It is done once the drive is prepared, so a copy that
        # cannot be kept never costs the preparation itself.
        if loader_from is not None and data.get("saveLoaders"):
            result["savedLoaders"] = service.save_boot_chain(
                loader_from, str(data.get("driver") or DRIVERLESS),
            )
        return jsonify(image=service.summary(session), **result)

    @blueprint.post("/api/images/<image_id>/install/desktop")
    @image_mutation("installing an application on the desktop")
    def install_desktop(image_id):
        """Put one program on the desktop and tell GEM how to start it."""
        data = payload()
        session = service.get(image_id)
        apply_partition(service, session, data.get("partition"))
        program = str(data.get("program") or "").strip()
        if not program:
            raise DiskError("Choose the program the desktop should install.")
        result = service.install_desktop_application(
            session,
            program,
            documents=str(data.get("documents") or ""),
            label=str(data.get("label") or ""),
            on_desktop=data.get("onDesktop", True) is not False,
        )
        return jsonify(image=service.summary(session), desktop=result)

    def _chosen_folder(value):
        """A folder the operator picked for this one install, or the usual ones.

        Someone who has just downloaded a desktop has it in their downloads
        folder, not in the directory this application keeps copies in. Pointing
        at that folder for one install is less trouble than moving files
        about, so an absent or empty value means the usual directories and
        anything else means search there instead.
        """
        text = str(value or "").strip()
        if not text:
            return None
        folder = Path(text).expanduser()
        if not folder.exists():
            raise DiskError(f"{folder} is not a folder on this computer.")
        return [folder]

    @blueprint.get("/api/install/desktops")
    def desktop_replacements():
        """The replacement desktops, and which one suits the machine asked about.

        The built-in TOS desktop cannot be replaced by anything this ships,
        because three of these four belong to somebody. What it can do is
        install the operator's own copy and say which one is the sensible
        choice for the machine the drive is being built for, which is the part
        that otherwise takes an evening of reading forum posts.
        """
        machine = str(request.args.get("machine") or "st")
        try:
            memory = int(request.args.get("memory") or 0)
        except ValueError:
            memory = 0
        return jsonify(
            desktops=describe_desktops(),
            available=service.available_desktops(_chosen_folder(request.args.get("folder"))),
            recommended=recommended_desktop(machine, memory),
            default=NO_DESKTOP,
        )

    @blueprint.post("/api/images/<image_id>/install/desktop-replacement")
    @image_mutation("installing a replacement desktop")
    def install_desktop_replacement(image_id):
        """Copy a replacement desktop onto this drive and install it."""
        data = payload()
        session = service.get(image_id)
        apply_partition(service, session, data.get("partition"))
        result = service.install_desktop_replacement(
            session,
            str(data.get("desktop") or ""),
            on_desktop=data.get("onDesktop", True) is not False,
            directories=_chosen_folder(data.get("folder")),
            download=data.get("download", True) is not False,
        )
        return jsonify(image=service.summary(session), desktop=result)

    @blueprint.post("/api/images/<image_id>/install/preparation")
    @request_effect("read-only", "reading how a drive has been prepared")
    def preparation(image_id):
        """Report a drive's preparation for a partition chosen in the request."""
        data = payload()
        session = service.get(image_id)
        apply_partition(service, session, data.get("partition"))
        return jsonify(preparation=service.drive_preparation(session))

    return blueprint
