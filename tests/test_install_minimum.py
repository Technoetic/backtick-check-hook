"""Check the installation boundary on Python versions below the supported minimum."""
import json
import sys
import unittest

from isolated_home import INSTALLER, IsolatedHome


class MinimumPythonTests(unittest.TestCase):
    def setUp(self):
        self.home = IsolatedHome(self)

    def older_python(self, action, host):
        args = [sys.executable, "-I", "-X", "utf8", "-B"]
        if sys.version_info >= (3, 11):
            # On a supported runner, exercise the same CLI with the old version tuple.
            args.extend(["-c", "import runpy,sys; sys.version_info=(3,10,11); "
                         "sys.argv=sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')"])
        return self.home.run([*args, str(INSTALLER), action, "--host", host])

    def test_old_python_refuses_install_before_writing(self):
        for host in self.home.configs:
            with self.subTest(host=host):
                proc = self.older_python("install", host)
                self.assertEqual(proc.returncode, 1)
                self.assertIn(b"Python 3.11", proc.stderr)
                self.assertFalse(self.home.configs[host].exists())
                self.assertFalse(self.home.package(host).exists())

    def test_old_python_doctor_explains_required_version(self):
        for host in self.home.configs:
            with self.subTest(host=host):
                proc = self.older_python("doctor", host)
                self.assertEqual(proc.returncode, 1)
                result = json.loads(proc.stdout)
                self.assertEqual(result["synthetic"], "not-run")
                self.assertTrue(any("Python 3.11" in item for item in result["warnings"]))
                self.assertFalse(self.home.configs[host].exists())
