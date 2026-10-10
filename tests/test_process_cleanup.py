import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from flexboot.process import Runner
from flexboot.targets import attached_image


class CleanupTests(unittest.TestCase):
    def test_loop_detached_after_exception(self):
        calls = []
        def fake_run(self, argv, **kwargs):
            import subprocess
            calls.append(list(argv))
            if argv[0] == "losetup" and "--show" in argv:
                return subprocess.CompletedProcess(argv, 0, "/dev/loop99\n", "")
            return subprocess.CompletedProcess(argv, 0, "", "")
        with tempfile.TemporaryDirectory() as raw:
            image = Path(raw) / "x.img"; image.write_bytes(b"x")
            with patch.object(Runner, "run", fake_run), patch("flexboot.targets.assert_image_backing"):
                with self.assertRaises(RuntimeError):
                    with attached_image(image, Runner()): raise RuntimeError("boom")
        self.assertIn(["losetup", "--detach", "/dev/loop99"], calls)

    def test_unexpected_loop_backing_is_detached_before_writes(self):
        import subprocess
        from flexboot.errors import SafetyError
        calls=[]
        def fake_run(self,argv,**kwargs):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv,0,"/dev/loop99\n" if '--show' in argv else '', '')
        with tempfile.TemporaryDirectory() as raw:
            image=Path(raw)/'x.img';image.write_bytes(b'x')
            with patch.object(Runner,'run',fake_run),patch('flexboot.targets.assert_image_backing',side_effect=SafetyError('wrong image')):
                with self.assertRaises(SafetyError):
                    with attached_image(image,Runner()):self.fail('Must not reach write operations')
        self.assertIn(['losetup','--detach','/dev/loop99'],calls)

    def test_concurrent_image_writer_is_rejected_before_attach(self):
        import fcntl
        from flexboot.errors import SafetyError
        with tempfile.TemporaryDirectory() as raw:
            image=Path(raw)/'x.img';image.write_bytes(b'x')
            with image.open('rb') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                with patch.object(Runner,'run') as execute,self.assertRaises(SafetyError):
                    with attached_image(image,Runner()):self.fail('Must reject writer')
                execute.assert_not_called()


    def test_mount_unmount_attempted_even_if_flush_fails(self):
        import subprocess
        from flexboot.errors import CleanupError
        from flexboot.mounts import mounted
        active=False;calls=[]
        def run(self,argv,**kwargs):
            nonlocal active
            calls.append(list(argv))
            if argv[0]=='mount':active=True
            if argv[0]=='umount':active=False
            return subprocess.CompletedProcess(argv,0,'ext4' if argv[0]=='blkid' else '', '')
        with patch.object(Runner,'run',run),patch('flexboot.mounts.os.path.ismount',side_effect=lambda _:active),patch('flexboot.mounts.flush_filesystem',side_effect=OSError('injected flush failure')):
            with self.assertRaises(CleanupError):
                with mounted(Path('/dev/fixture'),runner=Runner()):pass
        self.assertTrue(any(c[0]=='umount' for c in calls))
        self.assertFalse(active)

    def test_sigterm_runs_cli_cleanup_and_restores_handler(self):
        import os,signal,contextlib,io
        from flexboot.cli import main
        previous=signal.getsignal(signal.SIGTERM)
        def terminate(_args):os.kill(os.getpid(),signal.SIGTERM)
        with patch('flexboot.cli.dispatch',side_effect=terminate),contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(main(['devices']),130)
        self.assertEqual(signal.getsignal(signal.SIGTERM),previous)



if __name__ == "__main__": unittest.main()
