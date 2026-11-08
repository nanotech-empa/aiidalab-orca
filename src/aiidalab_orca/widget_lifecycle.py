"""Dispose owned result widgets once, independently of the application shell."""


def close_widget_tree(widget):
    """Stop active viewers and close shared descendants only once.

    A panel can also dispose its own descendants through this function. Mark
    each widget before visiting its children so those calls remain idempotent.
    """
    if getattr(widget, '_orca_tree_closed', False):
        return
    widget._orca_tree_closed = True
    if hasattr(widget, 'set_active'):
        widget.set_active(False)
    for child in getattr(widget, 'children', ()):
        close_widget_tree(child)
    widget.close()
