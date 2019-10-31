import os.path
import sys
import re

from AnyQt.QtWidgets import QFileDialog, QGridLayout, QMessageBox

from Orange.widgets import gui, widget
from Orange.widgets.settings import Setting


_userhome = os.path.expanduser(f"~{os.sep}")


class OWSaveBase(widget.OWWidget, openclass=True):
    """
    Base class for Save widgets

    A derived class must provide, at minimum:

    - class `Inputs` and the corresponding handler that:

      - saves the input to an attribute `data`, and
      - calls `self.on_new_input`.

    - a class attribute `filters` with a list of filters or a dictionary whose
      keys are filters
    - method `do_save` that saves `self.data` into `self.filename`.

    Alternatively, instead of defining `do_save` a derived class can make
    `filters` a dictionary whose keys are classes that define a method `write`
    (like e.g. `TabReader`). Method `do_save` defined in the base class calls
    the writer corresponding to the currently chosen filter.

    A minimum example of derived class is
    `Orange.widgets.model.owsavemodel.OWSaveModel`.
    A more advanced widget that overrides a lot of base class behaviour is
    `Orange.widgets.data.owsave.OWSave`.
    """

    class Information(widget.OWWidget.Information):
        empty_input = widget.Msg("Empty input; nothing was saved.")

    class Error(widget.OWWidget.Error):
        no_file_name = widget.Msg("File name is not set.")
        general_error = widget.Msg("{}")

    want_main_area = False
    resizing_enabled = False

    last_dir = Setting("")
    filter = Setting("")  # default will be provided in __init__
    filename = Setting("", schema_only=True)
    auto_save = Setting(False)

    filters = []

    def __init__(self, start_row=0):
        """
        Set up the gui.

        The gui consists of a checkbox for auto save and two buttons put on a
        grid layout. Derived widgets that want to place controls above the auto
        save widget can set the `start_row` argument to the first free row,
        and this constructor will start filling the grid there.

        Args:
            start_row (int): the row at which to start filling the gui
        """
        super().__init__()
        self.data = None
        # This cannot be done outside because `filters` is defined by subclass
        if not self.filter:
            self.filter = next(iter(self.filters))

        self.grid = grid = QGridLayout()
        gui.widgetBox(self.controlArea, orientation=grid)
        grid.addWidget(
            gui.checkBox(
                None, self, "auto_save", "Autosave when receiving new data",
                callback=self.update_messages),
            start_row, 0, 1, 2)
        grid.setRowMinimumHeight(start_row + 1, 8)
        self.bt_save = gui.button(None, self, "Save", callback=self.save_file)
        grid.addWidget(self.bt_save, start_row + 2, 0)
        grid.addWidget(
            gui.button(None, self, "Save as ...", callback=self.save_file_as),
            start_row + 2, 1)

        self.adjustSize()
        self.update_messages()

    @property
    def writer(self):
        """
        Return the active writer

        The base class uses this property only in `do_save` to find the writer
        corresponding to the filter. Derived classes (e.g. OWSave) may also use
        it elsewhere.
        """
        return self.filters[self.filter]

    def on_new_input(self):
        """
        This method must be called from input signal handler.

        - It clears errors, warnings and information and calls
          `self.update_messages` to set the as needed.
        - It also calls `update_status` the can be overriden in derived
          methods to set the status (e.g. the number of input rows)
        - Calls `self.save_file` if `self.auto_save` is enabled and
          `self.filename` is provided.
        """
        self.Error.clear()
        self.Warning.clear()
        self.Information.clear()
        self.update_messages()
        self.update_status()
        if self.auto_save and self.filename:
            self.save_file()

    def save_file_as(self):
        """
        Ask the user for the filename and try saving the file
        """
        filename, selected_filter = self.get_save_filename()
        if not filename:
            return
        self.filename = filename
        self.filter = selected_filter
        self.last_dir = os.path.split(self.filename)[0]
        self.bt_save.setText(f"Save as {os.path.split(filename)[1]}")
        self.update_messages()
        self._try_save()

    def save_file(self):
        """
        If file name is provided, try saving, else call save_file_as
        """
        if not self.filename:
            self.save_file_as()
        else:
            self._try_save()

    def _try_save(self):
        """
        Private method that calls do_save within try-except that catches and
        shows IOError. Do nothing if not data or no file name.
        """
        self.Error.general_error.clear()
        if self.data is None or not self.filename:
            return
        try:
            self.do_save()
        except IOError as err_value:
            self.Error.general_error(str(err_value))

    def do_save(self):
        """
        Do the saving.

        Default implementation calls the write method of the writer
        corresponding to the current filter. This requires that class attribute
        filters is a dictionary whose keys are classes.

        Derived classes may simplify this by providing a list of filters and
        override do_save. This is particularly handy if the widget supports only
        a single format.
        """
        # This method is separated out because it will usually be overriden
        self.writer.write(self.filename, self.data)

    def update_messages(self):
        """
        Update errors, warnings and information.

        Default method sets no_file_name if auto_save is enabled but file name
        is not provided; and empty_input if file name is given but there is no
        data.

        Derived classes that define further messages will typically set them in
        this method.
        """
        self.Error.no_file_name(shown=not self.filename and self.auto_save)
        self.Information.empty_input(shown=self.filename and self.data is None)

    def update_status(self):
        """
        Update the input/output indicator. Default method does nothing.
        """

    def initial_start_dir(self):
        """
        Provide initial start directory

        Return either the current file's path, the last directory or home.
        """
        if self.filename and os.path.exists(os.path.split(self.filename)[0]):
            return self.filename
        else:
            return self.last_dir or _userhome

    @staticmethod
    def suggested_name():
        """
        Suggest the name for the output file or return an empty string.
        """
        return ""

    @classmethod
    def _replace_extension(cls, filename, extension):
        """
        Remove all extensions that appear in any filter.

        Double extensions are broken in different weird ways across all systems,
        including omitting some, like turning iris.tab.gz to iris.gz. This
        function removes anything that can appear anywhere.
        """
        known_extensions = set()
        for filt in cls.filters:
            known_extensions |= set(cls._extension_from_filter(filt).split("."))
        if "" in known_extensions:
            known_extensions.remove("")
        while True:
            base, ext = os.path.splitext(filename)
            if ext[1:] not in known_extensions:
                break
            filename = base
        return filename + extension

    @staticmethod
    def _extension_from_filter(selected_filter):
        return re.search(r".*\(\*?(\..*)\)$", selected_filter).group(1)

    def valid_filters(self):
        return self.filters

    def default_valid_filter(self):
        return self.filter

    # As of Qt 5.9, QFileDialog.setDefaultSuffix does not support double
    # suffixes, not even in non-native dialogs. We handle each OS separately.
    if sys.platform in ("darwin", "win32"):
        # macOS and Windows native dialogs do not correctly handle double
        # extensions. We thus don't pass any suffixes to the dialog and add
        # the correct suffix after closing the dialog and only then check
        # if the file exists and ask whether to override.
        # It is a bit confusing that the user does not see the final name in the
        # dialog, but I see no better solution.
        def get_save_filename(self):  # pragma: no cover
            if sys.platform == "darwin":
                def remove_star(filt):
                    return filt.replace(" (*.", " (.")
            else:
                def remove_star(filt):
                    return filt

            no_ext_filters = {remove_star(f): f for f in self.valid_filters()}
            filename = self.initial_start_dir()
            while True:
                dlg = QFileDialog(
                    None, "Save File", filename, ";;".join(no_ext_filters))
                dlg.setAcceptMode(dlg.AcceptSave)
                dlg.selectNameFilter(remove_star(self.default_valid_filter()))
                dlg.setOption(QFileDialog.DontConfirmOverwrite)
                if dlg.exec() == QFileDialog.Rejected:
                    return "", ""
                filename = dlg.selectedFiles()[0]
                selected_filter = no_ext_filters[dlg.selectedNameFilter()]
                filename = self._replace_extension(
                    filename, self._extension_from_filter(selected_filter))
                if not os.path.exists(filename) or QMessageBox.question(
                        self, "Overwrite file?",
                        f"File {os.path.split(filename)[1]} already exists.\n"
                        "Overwrite?") == QMessageBox.Yes:
                    return filename, selected_filter

    else:  # Linux and any unknown platforms
        # Qt does not use a native dialog on Linux, so we can connect to
        # filterSelected and to overload selectFile to change the extension
        # while the dialog is open.
        # For unknown platforms (which?), we also use the non-native dialog to
        # be sure we know what happens.
        class SaveFileDialog(QFileDialog):
            # pylint: disable=protected-access
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.suffix = ""
                self.setAcceptMode(QFileDialog.AcceptSave)
                self.setOption(QFileDialog.DontUseNativeDialog)
                self.filterSelected.connect(self.updateDefaultExtension)

            def selectNameFilter(self, selected_filter):
                super().selectNameFilter(selected_filter)
                self.updateDefaultExtension(selected_filter)

            def updateDefaultExtension(self, selected_filter):
                self.suffix = OWSaveBase._extension_from_filter(selected_filter)
                files = self.selectedFiles()
                if files and not os.path.isdir(files[0]):
                    self.selectFile(files[0])

            def selectFile(self, filename):
                filename = OWSaveBase._replace_extension(filename, self.suffix)
                super().selectFile(filename)

        def get_save_filename(self):
            dlg = self.SaveFileDialog(
                None, "Save File", self.initial_start_dir(),
                ";;".join(self.valid_filters()))
            dlg.selectNameFilter(self.default_valid_filter())
            if dlg.exec() == QFileDialog.Rejected:
                return "", ""
            else:
                return dlg.selectedFiles()[0], dlg.selectedNameFilter()
