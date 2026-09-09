from pathlib import Path
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]


class ContainerDefinitionTests(unittest.TestCase):
    @staticmethod
    def _python_stages(dockerfile: str) -> tuple[int, int]:
        builder = dockerfile.index(" AS python-deps")
        builder = dockerfile.rfind("FROM python:", 0, builder)
        runtime = dockerfile.rindex("FROM python:")
        return builder, runtime

    def test_python_native_dependencies_are_built_outside_runtime_image(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        builder, runtime = self._python_stages(dockerfile)
        self.assertLess(builder, runtime)
        self.assertIn("build-essential", dockerfile[builder:runtime])
        self.assertIn("--root=/python-install", dockerfile[builder:runtime])
        self.assertIn('sysconfig.get_path("purelib")', dockerfile[builder:runtime])
        self.assertIn(
            "Staged Capstone 68000/68020/68040 support is available",
            dockerfile[builder:runtime],
        )
        runtime_definition = dockerfile[runtime:]
        self.assertIn("COPY --from=python-deps /python-install/usr/local /usr/local", runtime_definition)
        self.assertNotIn("/wheels", runtime_definition)
        self.assertNotIn("build-essential", runtime_definition)

    def test_the_runtime_image_carries_the_bundled_engine(self):
        """The engine ships in the repository, so it must reach the image."""
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        _builder, runtime = self._python_stages(dockerfile)
        runtime_definition = dockerfile[runtime:]
        self.assertIn("COPY atarinut ./atarinut", runtime_definition)
        self.assertIn("import atarinut", runtime_definition)

    def test_no_atari_tos_firmware_is_shipped_or_downloaded(self):
        """Atari TOS is not redistributable, so no build step may fetch one.

        EmuTOS is different: it is GPL, so the bundled images under
        ``firmware/emutos/`` are tracked on purpose and are the only ROMs the
        repository may carry. The check is on what the repository *tracks*,
        not on what happens to be in the directory. ``firmware/tos/`` is where
        an operator is told to put their own TOS ROMs so the emulator can find
        them, and it is ignored by git for exactly that reason. Reading the
        directory instead would fail on any machine that had followed those
        instructions, which is the wrong way round: the working copy is
        allowed to hold ROMs, and the public repository is not.
        """
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
        for forbidden in ("tos100", "tos104", "tos206", "tos404", "tos.img", "atari-tos", "firmware/tos"):
            self.assertNotIn(forbidden, dockerfile.lower())
        try:
            listed = subprocess.run(
                ["git", "ls-files", "firmware"],
                cwd=ROOT, capture_output=True, text=True, check=True, timeout=30,
            ).stdout.split()
        except (OSError, subprocess.SubprocessError):
            # An export or a source tarball has no git metadata. There is
            # nothing to check there, because nothing can be committed from it.
            self.skipTest("this working copy is not a git repository")
        if not listed:
            self.skipTest("nothing is committed yet")
        self.assertIn("firmware/README.md", listed)
        for tracked in listed:
            self.assertTrue(
                tracked == "firmware/README.md" or tracked.startswith("firmware/emutos/"),
                f"{tracked} must not be committed: only EmuTOS may be tracked",
            )
        self.assertTrue(any(name.startswith("firmware/emutos/etos") for name in listed))

    def test_public_clone_instructions_do_not_require_a_github_key(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn("git clone https://github.com/peteclarke-del/AtariFileForge.git", readme)


if __name__ == "__main__":
    unittest.main()
