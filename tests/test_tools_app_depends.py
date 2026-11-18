import json
import os
import shutil
import subprocess
import tempfile
import unittest

TOOLS = os.path.join(os.path.dirname(__file__), '..', 'files', '3-rinkhals', 'tools.sh')


@unittest.skipUnless(shutil.which('bash') and shutil.which('jq'), 'needs bash and jq')
class AppDependsTests(unittest.TestCase):
    """The app dependency rules in tools.sh, run against a throwaway app tree."""

    def setUp(self):
        self.root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.root)
        self.builtin = os.path.join(self.root, 'builtin')
        self.home = os.path.join(self.root, 'home')
        self.user = os.path.join(self.home, 'apps')
        os.makedirs(self.builtin)
        os.makedirs(self.user)

    def app(self, name, depends=None, enabled=False, builtin=False, comment=False):
        path = os.path.join(self.builtin if builtin else self.user, name)
        os.makedirs(path)
        manifest = {'$version': '1', 'name': name, 'version': '1.0'}
        if depends is not None:
            manifest['depends'] = depends
        text = json.dumps(manifest, indent=4)
        if comment:
            text = '// some apps carry comments\n' + text
        with open(os.path.join(path, 'app.json'), 'w') as f:
            f.write(text)
        with open(os.path.join(path, 'app.sh'), 'w') as f:
            f.write('#!/bin/sh\n')
        if enabled:
            open(os.path.join(path, '.enabled'), 'w').close()

    def sh(self, script):
        """Run script with tools.sh loaded and pointed at the test tree."""
        full = (f'. "{TOOLS}" > /dev/null 2>&1\n'
                f'RINKHALS_HOME="{self.home}"\nBUILTIN_APP_PATH="{self.builtin}"\nUSER_APP_PATH="{self.user}"\n'
                + script)
        r = subprocess.run(['bash', '-c', full], capture_output=True, text=True)
        return r.returncode, r.stdout.strip()

    def test_depends_are_read_from_the_manifest(self):
        self.app('screen', depends=['klipper', 'other'], comment=True)
        self.app('plain')
        self.assertEqual(self.sh('get_app_depends screen')[1].split(), ['klipper', 'other'])
        self.assertEqual(self.sh('get_app_depends plain')[1], '')
        self.assertEqual(self.sh('get_app_depends missing')[1], '')

    def test_enable_needs_the_dependency_installed_and_enabled(self):
        self.app('screen', depends=['klipper'])

        code, out = self.sh('enable_app screen')
        self.assertNotEqual(code, 0)
        self.assertIn('klipper', out)
        self.assertEqual(self.sh('is_app_enabled screen')[1], '0')

        self.app('klipper')  # installed but not enabled
        self.assertNotEqual(self.sh('enable_app screen')[0], 0)

        self.assertEqual(self.sh('enable_app klipper && enable_app screen')[0], 0)
        self.assertEqual(self.sh('is_app_enabled screen')[1], '1')

    def test_disable_is_refused_while_an_enabled_app_depends_on_it(self):
        self.app('klipper', enabled=True)
        self.app('screen', depends=['klipper'], enabled=True)

        code, out = self.sh('disable_app klipper')
        self.assertNotEqual(code, 0)
        self.assertIn('screen', out)
        self.assertEqual(self.sh('is_app_enabled klipper')[1], '1')

        # Disabling the dependent first frees it, and so does "force".
        self.assertEqual(self.sh('disable_app screen && disable_app klipper')[0], 0)
        self.assertEqual(self.sh('is_app_enabled klipper')[1], '0')

    def test_force_disables_regardless(self):
        self.app('klipper', enabled=True)
        self.app('screen', depends=['klipper'], enabled=True)
        self.assertEqual(self.sh('disable_app klipper force')[0], 0)
        self.assertEqual(self.sh('is_app_enabled klipper')[1], '0')

    def test_dependents_cover_user_and_builtin_apps(self):
        self.app('klipper', enabled=True)
        self.app('screen', depends=['klipper'], enabled=True)
        self.app('30-helper', depends=['klipper'], builtin=True)
        self.app('unrelated', depends=[])
        self.assertEqual(sorted(self.sh('get_app_dependents klipper')[1].split()), ['30-helper', 'screen'])
        self.assertEqual(self.sh('get_app_dependents klipper enabled')[1].split(), ['screen'])
        self.assertEqual(self.sh('get_app_dependents screen')[1], '')

    def test_apps_without_depends_are_unaffected(self):
        self.app('plain')
        self.assertEqual(self.sh('enable_app plain && disable_app plain')[0], 0)

    def test_start_order_puts_dependencies_first(self):
        self.app('a-screen', depends=['z-klipper'])
        self.app('m-plain')
        self.app('z-klipper', depends=['10-base'])
        self.app('10-base', builtin=True)
        order = self.sh('list_apps_in_start_order')[1].split()
        self.assertEqual(sorted(order), ['10-base', 'a-screen', 'm-plain', 'z-klipper'])
        self.assertLess(order.index('10-base'), order.index('z-klipper'))
        self.assertLess(order.index('z-klipper'), order.index('a-screen'))

    def test_start_order_survives_a_loop_and_a_missing_dependency(self):
        self.app('a', depends=['b'])
        self.app('b', depends=['a'])
        self.app('c', depends=['not-installed'])
        self.assertEqual(sorted(self.sh('list_apps_in_start_order')[1].split()), ['a', 'b', 'c'])


if __name__ == '__main__':
    unittest.main()
