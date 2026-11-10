"""Regressions based on the user's actual Maya/i3 window properties."""
import copy
import importlib.util
from pathlib import Path
from types import SimpleNamespace
import unittest

spec = importlib.util.spec_from_file_location(
    'maya_panels', Path(__file__).resolve().parents[1] / 'scripts/helpers/maya-i3-panels.py')
panels = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panels)


def window(window_id, container, transient=None, floating='auto_off'):
    return {'id': container, 'window': window_id, 'type': 'con',
            'window_properties': {'class': 'Maya-2027', 'instance': 'maya.bin',
                                  'window_role': None, 'transient_for': transient},
            'window_type': 'normal', 'floating': floating, 'fullscreen_mode': 0,
            'rect': {'x': 1920, 'y': 49, 'width': 1920, 'height': 1031},
            'geometry': {'x': 1920, 'y': 49, 'width': 600, 'height': 400}}


class MayaPanelTests(unittest.TestCase):
    def setUp(self):
        self.main = window(94372007, 94246171463360)
        self.panel = window(94374214, 94246171480864, transient=94372007)
        self.tree = {'type': 'root', 'nodes': [
            {'type': 'workspace', 'rect': copy.deepcopy(self.main['rect']),
             'nodes': [self.main, self.panel], 'floating_nodes': []}]}

    def test_observed_identical_class_and_absent_roles_only_float_panel(self):
        self.assertEqual(panels.adjustments(self.tree),
                         [(94246171480864, 'floating enable')])

    def test_main_window_without_transient_is_never_changed(self):
        self.tree['nodes'][0]['nodes'] = [self.main]
        self.assertEqual(panels.adjustments(self.tree), [])

    def test_manual_tiling_and_existing_floating_are_respected(self):
        for state in ('user_off', 'user_on', 'auto_on'):
            with self.subTest(state=state):
                self.panel['floating'] = state
                self.assertEqual(panels.adjustments(self.tree), [])

    def test_other_application_and_foreign_parent_are_ignored(self):
        self.main['window_properties']['class'] = 'OtherProgram'
        self.assertEqual(panels.adjustments(self.tree), [])
        self.main['window_properties']['class'] = 'Maya-2027'
        self.panel['window_properties']['instance'] = 'unrelated.bin'
        self.assertEqual(panels.adjustments(self.tree), [])

    def test_missing_transient_parent_is_ignored(self):
        self.panel['window_properties']['transient_for'] = 12345
        self.assertEqual(panels.adjustments(self.tree), [])

    def test_tooltips_and_intentional_fullscreen_are_ignored(self):
        self.panel['window_type'] = 'tooltip'
        self.assertEqual(panels.adjustments(self.tree), [])
        self.panel['window_type'] = 'normal'
        self.panel['fullscreen_mode'] = 1
        self.assertEqual(panels.adjustments(self.tree), [])

    def test_full_workspace_geometry_is_reduced_for_the_panel_only(self):
        self.panel['geometry'] = copy.deepcopy(self.main['rect'])
        result = panels.adjustments(self.tree)
        self.assertEqual(len(result), 1)
        container, command = result[0]
        self.assertEqual(container, self.panel['id'])
        self.assertIn('floating enable, resize set', command)
        self.assertNotIn('1920', command)
        self.assertNotIn('1031', command)

    def test_reconcile_addresses_only_the_observed_panel_container(self):
        commands = []
        connection = SimpleNamespace(
            get_tree=lambda: SimpleNamespace(ipc_data=self.tree),
            command=lambda text: commands.append(text) or [SimpleNamespace(success=True)])
        self.assertEqual(panels.reconcile(connection), 1)
        self.assertEqual(commands, ['[con_id=94246171480864] floating enable'])

    def test_failed_i3_command_is_reported(self):
        connection = SimpleNamespace(
            get_tree=lambda: SimpleNamespace(ipc_data=self.tree),
            command=lambda _: [SimpleNamespace(success=False)])
        with self.assertRaises(RuntimeError): panels.reconcile(connection)


if __name__ == '__main__':
    unittest.main()
