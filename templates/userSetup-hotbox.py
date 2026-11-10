# BEGIN maya-debian-hotbox
def _schedule_maya_hotbox_fix():
    import os
    from maya import cmds, utils

    if cmds.about(batch=True) or os.environ.get('MAYA_HOTBOX_GEOMETRY_FIX', '1') == '0':
        return

    def activate():
        try:
            import runpy
            fix = runpy.run_path(__MAYA_HOTBOX_SCRIPT__)
            fix['install'](quiet=True)
        except Exception as error:
            cmds.warning('Hotbox-Flaechenkorrektur konnte nicht starten: ' + str(error))

    utils.executeDeferred(activate)


_schedule_maya_hotbox_fix()
del _schedule_maya_hotbox_fix
# END maya-debian-hotbox
