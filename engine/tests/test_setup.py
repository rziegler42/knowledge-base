import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from engine.tests import ENGINE_DIR

from kb import KbError, config, library


def read_json(path):
    with open(path) as f:
        return json.load(f)


def write_json(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f)


def read_text(path):
    with open(path) as f:
        return f.read()


def real_tmp():
    """A temporary folder whose path holds no symlink (macOS keeps /var as a link to /private/var)."""
    d = tempfile.TemporaryDirectory()
    return d, os.path.realpath(d.name)


class SetupTest(unittest.TestCase):
    def setUp(self):
        self._tmp, self.base = real_tmp()
        self.addCleanup(self._tmp.cleanup)
        self.cfg = os.path.join(self.base, "cfg")
        self.bulk = os.path.join(self.base, "bulk")
        self.index = os.path.join(self.base, "index")
        self._saved = os.environ.get("KB_CONFIG_DIR")
        os.environ["KB_CONFIG_DIR"] = self.cfg
        self.addCleanup(self._restore_env)

    def _restore_env(self):
        if self._saved is None:
            os.environ.pop("KB_CONFIG_DIR", None)
        else:
            os.environ["KB_CONFIG_DIR"] = self._saved

    def setup_lib(self, **kw):
        kw.setdefault("allow_main_disk", True)
        return library.setup(self.bulk, self.index, **kw)

    # --- a first setup
    def test_setup_creates_config_marker_and_index(self):
        lib_id = self.setup_lib()
        self.assertRegex(lib_id, r"^[0-9a-f]{32}$")
        cfg_file = os.path.join(self.cfg, "config.json")
        self.assertEqual(stat.S_IMODE(os.stat(cfg_file).st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(os.stat(self.cfg).st_mode), 0o700)
        cfg = read_json(cfg_file)
        self.assertEqual(cfg["library_id"], lib_id)
        self.assertEqual(cfg["bulk_root"], self.bulk)
        self.assertEqual(cfg["index_root"], self.index)
        self.assertEqual(cfg["bulk_device"], os.stat(self.bulk).st_dev)
        self.assertEqual(cfg["format"], library.FORMAT)
        marker = read_json(os.path.join(self.bulk, library.MARKER))
        self.assertEqual(marker["library_id"], lib_id)
        self.assertTrue(os.path.isdir(self.index))
        self.assertEqual(read_json(os.path.join(self.index, "format.json"))["format"], library.FORMAT)

    def test_config_directory_comes_from_the_environment_variable(self):
        self.setup_lib()
        self.assertTrue(os.path.isfile(os.path.join(self.cfg, "config.json")))

    # --- repeating a setup
    def test_setup_twice_with_the_same_roots_keeps_the_id(self):
        first = self.setup_lib()
        before = read_text(os.path.join(self.cfg, "config.json"))
        second = self.setup_lib()
        self.assertEqual(first, second)
        self.assertEqual(before, read_text(os.path.join(self.cfg, "config.json")))

    def test_setup_with_other_roots_after_a_setup_is_refused(self):
        self.setup_lib()
        with self.assertRaises(KbError) as cm:
            library.setup(os.path.join(self.base, "bulk2"), os.path.join(self.base, "index2"), allow_main_disk=True)
        self.assertIn("already", str(cm.exception))

    # --- refusals
    def test_root_holding_another_librarys_marker_is_refused_and_no_config_is_written(self):
        os.makedirs(self.bulk)
        write_json(os.path.join(self.bulk, library.MARKER), {"format": 1, "library_id": "f" * 32})
        with self.assertRaises(KbError) as cm:
            self.setup_lib()
        self.assertIn("another library", str(cm.exception))
        self.assertFalse(os.path.exists(os.path.join(self.cfg, "config.json")))

    def test_symlinked_root_is_refused(self):
        real = os.path.join(self.base, "real")
        os.makedirs(real)
        os.symlink(real, self.bulk)
        with self.assertRaises(KbError) as cm:
            self.setup_lib()
        self.assertIn("symlink", str(cm.exception))

    def test_symlink_in_the_path_of_a_root_is_refused(self):
        real = os.path.join(self.base, "real")
        os.makedirs(real)
        link = os.path.join(self.base, "link")
        os.symlink(real, link)
        with self.assertRaises(KbError) as cm:
            library.setup(os.path.join(link, "bulk"), self.index, allow_main_disk=True)
        self.assertIn("symlink", str(cm.exception))

    def test_the_same_folder_for_both_roots_is_refused(self):
        with self.assertRaises(KbError) as cm:
            library.setup(self.bulk, self.bulk, allow_main_disk=True)
        self.assertIn("same folder", str(cm.exception))

    def test_roots_that_differ_only_in_letter_case_are_the_same_folder(self):
        with self.assertRaises(KbError) as cm:
            library.setup(os.path.join(self.base, "Lib"), os.path.join(self.base, "lib"), allow_main_disk=True)
        self.assertIn("same folder", str(cm.exception))

    def test_a_failed_setup_takes_back_its_marker_so_a_rerun_works(self):
        with mock.patch.object(config, "save", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.setup_lib()
        self.assertFalse(os.path.exists(os.path.join(self.bulk, library.MARKER)))
        self.assertFalse(os.path.exists(os.path.join(self.index, "format.json")))
        self.assertRegex(self.setup_lib(), r"^[0-9a-f]{32}$")

    def test_a_stale_temporary_file_does_not_block_a_write(self):
        os.makedirs(self.cfg)
        for name in ("config.json.tmp.%d" % os.getpid(), "config.json.tmp.0"):
            with open(os.path.join(self.cfg, name), "w") as f:
                f.write("stale")
        self.assertRegex(self.setup_lib(), r"^[0-9a-f]{32}$")

    def test_a_relative_root_is_refused(self):
        with self.assertRaises(KbError):
            library.setup("bulk", self.index, allow_main_disk=True)

    def test_a_root_on_the_main_disk_is_refused_unless_the_owner_allows_it(self):
        dev = os.stat(self.base).st_dev
        with self.assertRaises(KbError) as cm:
            library.setup(self.bulk, self.index, main_device=dev)
        self.assertIn("main disk", str(cm.exception))
        self.assertEqual(library.setup(self.bulk, self.index, main_device=dev, allow_main_disk=True),
                         config.load()["library_id"])

    # --- the config file
    def test_a_group_readable_config_is_refused_on_load(self):
        self.setup_lib()
        os.chmod(os.path.join(self.cfg, "config.json"), 0o640)
        with self.assertRaises(KbError) as cm:
            config.load()
        self.assertIn("owner-only", str(cm.exception))

    def test_a_symlinked_config_is_refused(self):
        self.setup_lib()
        real = os.path.join(self.base, "elsewhere.json")
        os.rename(os.path.join(self.cfg, "config.json"), real)
        os.symlink(real, os.path.join(self.cfg, "config.json"))
        with self.assertRaises(KbError) as cm:
            config.load()
        self.assertIn("symlink", str(cm.exception))

    def test_a_config_directory_writable_by_others_is_refused(self):
        self.setup_lib()
        os.chmod(self.cfg, 0o777)
        self.addCleanup(os.chmod, self.cfg, 0o700)
        with self.assertRaises(KbError) as cm:
            config.load()
        self.assertIn("writable by others", str(cm.exception))

    def test_a_config_owned_by_someone_else_is_refused(self):
        self.setup_lib()
        with mock.patch("os.getuid", return_value=os.getuid() + 1):
            with self.assertRaises(KbError) as cm:
                config.load()
        self.assertIn("not owned", str(cm.exception))

    def test_a_missing_config_is_reported(self):
        with self.assertRaises(KbError) as cm:
            config.load()
        self.assertIn("no library", str(cm.exception))


class WriteGuardTest(unittest.TestCase):
    def setUp(self):
        self._tmp, self.base = real_tmp()
        self.addCleanup(self._tmp.cleanup)
        self.cfg = os.path.join(self.base, "cfg")
        self.bulk = os.path.join(self.base, "bulk")
        self.index = os.path.join(self.base, "index")
        self._saved = os.environ.get("KB_CONFIG_DIR")
        os.environ["KB_CONFIG_DIR"] = self.cfg
        self.addCleanup(lambda: os.environ.pop("KB_CONFIG_DIR", None) if self._saved is None
                        else os.environ.__setitem__("KB_CONFIG_DIR", self._saved))
        self.lib_id = library.setup(self.bulk, self.index, allow_main_disk=True)

    def test_a_healthy_library_passes(self):
        self.assertEqual(library.check_writable()["library_id"], self.lib_id)

    def test_a_missing_marker_refuses_writes(self):
        os.remove(os.path.join(self.bulk, library.MARKER))
        with self.assertRaises(KbError) as cm:
            library.check_writable()
        self.assertIn("marker", str(cm.exception))

    def test_a_marker_with_another_id_refuses_writes(self):
        write_json(os.path.join(self.bulk, library.MARKER), {"format": 1, "library_id": "a" * 32})
        with self.assertRaises(KbError) as cm:
            library.check_writable()
        self.assertIn("marker", str(cm.exception))

    def test_a_changed_device_refuses_writes(self):
        recorded = os.stat(self.bulk).st_dev
        with self.assertRaises(KbError) as cm:
            library.check_writable(device_of=lambda path: recorded + 1)
        self.assertIn("device", str(cm.exception))

    def test_an_unreachable_bulk_root_refuses_writes(self):
        os.remove(os.path.join(self.bulk, library.MARKER))
        os.rmdir(self.bulk)
        with self.assertRaises(KbError) as cm:
            library.check_writable()
        self.assertIn("bulk root", str(cm.exception))

    def test_a_bulk_root_swapped_for_a_symlink_refuses_writes(self):
        moved = os.path.join(self.base, "moved")
        os.rename(self.bulk, moved)
        os.symlink(moved, self.bulk)
        with self.assertRaises(KbError) as cm:
            library.check_writable()
        self.assertIn("symlink", str(cm.exception))

    def test_a_library_that_may_not_be_on_the_main_disk_refuses_when_it_is(self):
        cfg = config.load()
        cfg["allow_main_disk"] = False
        config.save(cfg)
        with self.assertRaises(KbError) as cm:
            library.check_writable(main_device=os.stat(self.bulk).st_dev)
        self.assertIn("main disk", str(cm.exception))


class CommandLineTest(unittest.TestCase):
    def run_kb(self, cfg, *args):
        env = dict(os.environ, KB_CONFIG_DIR=cfg)
        return subprocess.run([sys.executable, "-m", "kb", *args], cwd=ENGINE_DIR, env=env,
                              capture_output=True, text=True, timeout=60)

    def test_setup_and_check_through_the_command_line(self):
        tmp, base = real_tmp()
        self.addCleanup(tmp.cleanup)
        cfg = os.path.join(base, "cfg")
        bulk, index = os.path.join(base, "bulk"), os.path.join(base, "index")
        done = self.run_kb(cfg, "setup", bulk, index, "--allow-main-disk")
        self.assertEqual(done.returncode, 0, done.stderr)
        out = json.loads(done.stdout)
        self.assertRegex(out["library_id"], r"^[0-9a-f]{32}$")
        ok = self.run_kb(cfg, "check")
        self.assertEqual(ok.returncode, 0, ok.stderr)
        self.assertEqual(json.loads(ok.stdout)["library_id"], out["library_id"])

    def test_the_rights_notice_is_shown_once_on_the_error_stream_only(self):
        tmp, base = real_tmp()
        self.addCleanup(tmp.cleanup)
        cfg = os.path.join(base, "cfg")
        bulk, index = os.path.join(base, "bulk"), os.path.join(base, "index")
        first = self.run_kb(cfg, "setup", bulk, index, "--allow-main-disk")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stderr, library.NOTICE + "\n")
        self.assertIn("responsib", library.NOTICE)
        self.assertEqual(list(json.loads(first.stdout)), ["library_id"])
        self.assertEqual(len(first.stdout.strip().splitlines()), 1)
        again = self.run_kb(cfg, "setup", bulk, index, "--allow-main-disk")
        self.assertEqual(again.returncode, 0)
        self.assertEqual(again.stderr, "")
        checked = self.run_kb(cfg, "check")
        self.assertEqual((checked.returncode, checked.stderr), (0, ""))

    def test_a_refused_setup_shows_no_notice(self):
        tmp, base = real_tmp()
        self.addCleanup(tmp.cleanup)
        same = os.path.join(base, "same")
        done = self.run_kb(os.path.join(base, "cfg"), "setup", same, same, "--allow-main-disk")
        self.assertEqual(done.returncode, 2)
        self.assertNotIn(library.NOTICE, done.stderr)

    def test_a_system_error_is_reported_without_a_traceback(self):
        tmp, base = real_tmp()
        self.addCleanup(tmp.cleanup)
        locked = os.path.join(base, "locked")
        os.makedirs(locked)
        os.chmod(locked, 0o500)
        self.addCleanup(os.chmod, locked, 0o700)
        done = self.run_kb(os.path.join(base, "cfg"), "setup", os.path.join(locked, "bulk"),
                           os.path.join(base, "index"), "--allow-main-disk")
        self.assertEqual(done.returncode, 1)
        self.assertTrue(done.stderr.startswith("failed: "), done.stderr)
        self.assertNotIn("Traceback", done.stderr)

    def test_a_refusal_exits_nonzero_with_the_reason(self):
        tmp, base = real_tmp()
        self.addCleanup(tmp.cleanup)
        cfg = os.path.join(base, "cfg")
        same = os.path.join(base, "same")
        done = self.run_kb(cfg, "setup", same, same, "--allow-main-disk")
        self.assertEqual(done.returncode, 2)
        self.assertTrue(done.stderr.startswith("refused: "), done.stderr)
        self.assertIn("same folder", done.stderr)


if __name__ == "__main__":
    unittest.main()
