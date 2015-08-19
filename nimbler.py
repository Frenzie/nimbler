#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
gi.require_version('Keybinder', '3.0')

from gi.repository import Gtk, GdkPixbuf, Wnck, Keybinder, Gdk, GdkX11, Pango
import re

# First try Python 3 configparser
try:
    import configparser
# Then try ConfigParser for Python 2 compatibility
except ImportError:
    import ConfigParser as configparser
import os
import signal
import string
from xml.sax.saxutils import escape

# Python GObject Introspection API Reference available at http://lazka.github.io/pgi-docs/
# Because after http://python-gtk-3-tutorial.readthedocs.org/en/latest/ it's really not that useful
# to try to guess things based on https://developer.gnome.org/gtk3/stable/ as suggested.

# Libwnck reference here: https://developer.gnome.org/libwnck/stable/

class FuzzyMatcher():

    def __init__(self):
        self.pattern = ''

    def setPattern(self, pattern):
        self.pattern = re.compile('.*?'.join(map(re.escape, list(pattern))))

    def score(self, string):
        match = self.pattern.search(string)
        if match is None:
            return 0
        else:
            return 100.0 * (1.0/(1 + match.start()) + 1.2/(match.end() - match.start() + 1))

class KeyBindings():
    
    def __init__(self):
        # That's 93 distinct characters on my system
        # Can't use string.printable because that includes string.whitespace
        self.numbering = string.digits + string.ascii_letters + string.punctuation.replace(':', '') # filter colon
        self.numbering = list(self.numbering)
        self.function_keys = ['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12']
        
    def get_keyvals_from_unicode(self):
        self.keyvals_from_unicode = []
        
        for number in self.numbering:
            unicode_character = ord(number)
            keyval = Gdk.unicode_to_keyval(unicode_character)
            self.keyvals_from_unicode.append(keyval)

        return self.keyvals_from_unicode
        
    def get_keyvals_from_name(self):
        self.keyvals_from_name = []
        
        for function_key in self.function_keys:
            keyval = Gdk.keyval_from_name(function_key)
            self.keyvals_from_name.append(keyval)

        return self.keyvals_from_name

class DPIScaling():

    def __init__(self):
        # Get the screen dpi
        self.dpi = Gdk.Screen.get_resolution(Gdk.Screen.get_default())
        # This is a scale factor between points specified in a Pango.FontDescription and cairo units. The default value is 96, meaning that a 10 point font will be 13 units high. (10 * 96. / 72. = 13.3).
        # See http://lazka.github.io/pgi-docs/#Gdk-3.0/classes/Screen.html#Gdk.Screen.set_resolution
        self.scaling_factor = self.dpi / 96

class WindowList():

    def __init__(self, ignored_windows, always_show_windows, ignored_window_types, icon_size):
        self.windowList = []
        self.max_windows = 0
        self.previousWindow = None
        self.fuzzyMatcher = FuzzyMatcher()
        self.ignored_windows = ignored_windows
        self.always_show_windows = always_show_windows
        self.ignored_window_types = ignored_window_types
        self.icon_size = icon_size

    def refresh(self):
        # Clear existing
        self.windowList = []

        # Get the screen and force update
        screen = Wnck.Screen.get_default()
        screen.force_update()
        
        # Get the workspaces
        self.workspace_count = Wnck.Screen.get_workspace_count(screen)
        self.workspaces = Wnck.Screen.get_workspaces(screen)
        self.active_workspace = Wnck.Screen.get_active_workspace(screen)
        
        # Set up the top list (is there a more efficient way?)
        for i in range(len(self.workspaces)):
            self.windowList.append([])

        # Get previous active window
        self.previousWindow = screen.get_active_window()

        # Get a list of windows
        window_list = screen.get_windows()
        for i in window_list:
            name = i.get_name()
            workspace = i.get_workspace()
            window_type = i.get_window_type()
            class_group = i.get_class_group_name()

            # Filter out extraneous windows
            if self.isWindowAlwaysShown(name):
                pass
            else:
                if window_type in self.ignored_window_types:
                    continue

                if self.isWindowIgnored(name):
                    continue
            
            # Construct workspace/window array
            #print('workspace ' + str(workspace) + name)
            #print('workspace index ' + str(self.workspaces.index(workspace)))
            # A window on every workspace will have workspace None
            if workspace:
                self.windowList[self.workspaces.index(workspace)].append({
                    'name': name,
                    'icon': self.get_icon(i),
                    'class_group': class_group,
                    'window': i, 'rank': 0
                })
            # Pretend the always on visible workspace window is on the active workspace
            else:
                self.windowList[self.workspaces.index(self.active_workspace)].append({
                    'name': name,
                    'icon': self.get_icon(i),
                    'class_group': class_group,
                    'window': i, 'rank': 0
                })
        
        # Determine the maximum amount of windows that needs to go under a specific workspace
        for i in self.windowList:
            if self.max_windows < len(i):
                self.max_windows = len(i)
                
        # Merged correctly ordered list for switching purposes
        # Via http://stackoverflow.com/a/952952
        self.window_list_merged = [item for sublist in self.windowList for item in sublist]

    def get_icon(self, window):
        if self.icon_size == 'default' or type(self.icon_size) is int:
            return window.get_icon()
        elif self.icon_size == 'mini':
            return window.get_mini_icon()
    
    def getLatest(self):
        self.refresh()
        return self.windowList

    def get(self):
        return self.windowList
        
    def get_max_windows(self):
        return self.max_windows
            
    def get_workspace_count(self):
        return self.workspace_count

    def getHighestRanked(self):
        if (len(self.windowList)):
            return self.windowList[0]

        return None

    def rank(self, text):
        self.fuzzyMatcher.setPattern(text.lower())
        for i in self.window_list_merged:
            score = self.fuzzyMatcher.score(i['name'].lower())
            if i['class_group']:
                score += self.fuzzyMatcher.score(i['class_group'].lower())
            i['rank'] = score

        self.window_list_merged.sort(key=lambda x: x['rank'], reverse=True)

    def getPreviousWindow(self):
        return self.previousWindow

    def isWindowIgnored(self, window_title):
        for pattern in self.ignored_windows:
            if pattern.search(window_title) is not None:
                return True

        return False

    def isWindowAlwaysShown(self, window_title):
        for pattern in self.always_show_windows:
            if pattern.search(window_title) is not None:
                return True

        return False


class NimblerWindow(Gtk.Window):

    def __init__(self, config):
        Gtk.Window.__init__(self, title='Nimbler')

        # Window is initially hidden
        self.hidden = True
        
        # Set up keybindings
        self.keybindings = KeyBindings()
        self.numbering = self.keybindings.numbering
        self.numbering_keyvals = self.keybindings.get_keyvals_from_unicode()
        self.function_keys_keyvals = self.keybindings.get_keyvals_from_name()
        # Set up keypad numbers dictionary
        self.keypad_numbers = {
            Gdk.KEY_KP_0: Gdk.KEY_0,
            Gdk.KEY_KP_1: Gdk.KEY_1,
            Gdk.KEY_KP_2: Gdk.KEY_2,
            Gdk.KEY_KP_3: Gdk.KEY_3,
            Gdk.KEY_KP_4: Gdk.KEY_4,
            Gdk.KEY_KP_5: Gdk.KEY_5,
            Gdk.KEY_KP_6: Gdk.KEY_6,
            Gdk.KEY_KP_7: Gdk.KEY_7,
            Gdk.KEY_KP_8: Gdk.KEY_8,
            Gdk.KEY_KP_9: Gdk.KEY_9,
        }
        
        # Set up the frame
        self.frame = Gtk.Frame()
        self.frame.set_shadow_type(1)
        self.add(self.frame)
        
        # Initialize window list
        self.windowList = WindowList(
            config.ignored_windows,
            config.always_show_windows,
            config.ignored_window_types,
            config.icon_size
        )
        # Needed for number of windows as well as making sure it's ready before drawing
        self.windowList.getLatest()

        # Register events
        self.connect("key-press-event", self.keypress)

    def populate(self, items):
        self.window_list = self.windowList.windowList
        self.window_counter = 0
        self.num_workspaces = len(self.window_list)

        dpi_scaling_factor = DPIScaling().scaling_factor
        
        for i in range(0, self.num_workspaces):
        #for i in range(0, self.workspaces):
            #print('window_list[i] '+str(window_list[i]))
            i_label = i + 1
            i_column_left = i * 2
            i_column_right = i_column_left + 2
            i_binding_right = i_column_left + 1
            
            workspace_button = Gtk.Button(label='Workspace ' + str(i_label))
            workspace_button.set_name('F' + str(i_label)) # Name is F1 and up to tie into keyboard event handling
            # The event handler likes a string
            workspace_button.connect('clicked', self.activate_workspace_via_button)
            
            self.table.attach(workspace_button, i_column_left, i_column_right, 0, 1)
            
            #for j in range(0, len(window_list[i])):
            for j in range(0, len(self.window_list[i])):
                j4table_left = j + 1
                j4table_right = j4table_left + 1
                name = self.window_list[i][j]['name']
                icon = self.window_list[i][j]['icon']
                binding = self.numbering[self.window_counter]
                
                # Shows what key to press
                binding_label = Gtk.Label()
                binding_label.set_padding(5, 0)
                if self.window_counter < len(self.numbering):
                    binding_label.set_markup('<b>' + escape(binding) + '</b>')
                self.table.attach(binding_label, i_column_left, i_binding_right, j4table_left, j4table_right)
                
                # Apparently buttons can only have one child, so we need a box
                # Useful info to be found at http://pygtk.org/pygtk2tutorial/ch-ButtonWidget.html
                # but keep in mind it's about Gtk+ 2 and also uses differently named Python objects
                button_box = Gtk.HBox(False, 0)
                image = Gtk.Image.new_from_pixbuf(icon)
                button_label = Gtk.Label(name)
                button_label.set_alignment(0, 0.5) # first attribute is horizontal, second is vertical
                #button_label.set_max_width_chars(256) # not working, why?
                # TODO Make configurable?
                button_label.set_ellipsize(Pango.EllipsizeMode.MIDDLE)
                
                # Pack 'em in
                button_box.pack_start(image, False, False, 3)
                button_box.pack_start(button_label, False, False, 3)
                
                # The all important window button
                button = Gtk.Button()
                button.set_relief(Gtk.ReliefStyle.NONE)
                button.set_size_request((dpi_scaling_factor * 256), -1)
                button.set_name(binding)
                button.connect('clicked', self.present_window_via_button)
                
                # Add the content to the button
                button.add(button_box)
                self.table.attach(button, i_binding_right, i_column_right, j4table_left, j4table_right)
                
                # Up the overall counter
                self.window_counter += 1
    
    def activate_workspace(self, label):
        # Ignore everything in the supplied string but the numbers
        workspace = re.sub('[^0-9]', '', label)
        workspace = int(workspace) - 1
        
        self.toggle()
        self.windowList.workspaces[workspace].activate(self.getXTime())
    
    def activate_workspace_via_button(self, button):
        name = button.get_name()
        self.activate_workspace(name)
        
    def enteredNameChanged(self, entry):
        text = entry.get_text()
        if text:
            self.windowList.rank(text)
            self.populate(self.windowList.get())

    def close_window(self, window):
        window.close(self.getXTime())

    def close_window_via_number(self, window_number):
        self.toggle()
        self.close_window(
            self.windowList.window_list_merged[window_number]['window']
        )

    def presentWindow(self, window):
        workspace = window.get_workspace()
        if workspace is not None:
            workspace.activate(self.getXTime())

        window.activate(self.getXTime())
    
    def present_window_via_button(self, button):
        name = button.get_name()
        window_number = self.numbering.index(name)
        self.present_window_via_number(window_number)
    
    def present_window_via_number(self, window_number):
        self.toggle()
        self.presentWindow(
            self.windowList.window_list_merged[window_number]['window']
        )

    def presentHighestRanked(self):
        highestRanked = self.windowList.getHighestRanked()
        if highestRanked is not None:
            self.presentWindow(highestRanked['window'])

    def presentManual(self, view, path, column):
        indices = path.get_indices()
        if len(indices) < 1:
            return

        index = indices[0]
        windows = self.windowList.get()
        if index < len(windows):
            self.toggle()
            self.presentWindow(windows[index]['window'])

    def keypress(self, widget, event):
        # Support pressing numbers on keypad
        # If event.keyval is found in the dictionary of keypad numbers it'll change it into a regular number;
        # otherwise it simply returns event.keyval
        # Thanks to http://stackoverflow.com/a/103081
        event.keyval = self.keypad_numbers.get(event.keyval, event.keyval)
        
        #selected = self.appListView.get_selection().get_selected()
        if event.keyval == Gdk.KEY_Escape:
            self.toggle()
        # Workspace shortcuts
        elif event.keyval in self.function_keys_keyvals[:self.num_workspaces]:
            self.activate_workspace(
                self.keybindings.function_keys[self.keybindings.get_keyvals_from_name().index(event.keyval)]
            )
        elif not self.enteredName.has_focus():
            # Window shortcuts
            if event.keyval in self.numbering_keyvals[:self.window_counter]:
                if event.get_state() & Gdk.ModifierType.CONTROL_MASK:
                    self.close_window_via_number(self.numbering_keyvals.index(event.keyval))
                else:
                    self.present_window_via_number(self.numbering_keyvals.index(event.keyval))
            elif event.keyval == Gdk.KEY_colon:
                # Show input, thanks to http://stackoverflow.com/a/4956770
                self.enteredName.show()
                self.enteredName.grab_focus()
                # Return True so the colon doesn't end up in the Entry box
                return True
        # The text input has focus
        else:
            if event.keyval == Gdk.KEY_Return:
                # TODO do something!
                print('enter pressed in input')
        
    def toggle(self):
        if self.hidden:
            self.windowList.refresh()
            self.max_windows = self.windowList.get_max_windows() #change
            self.workspaces = len(self.windowList.get()) #bit illogical naming going on here
            
            self.table = Gtk.Table(self.max_windows, self.workspaces * 2, False)
            self.table.set_name('NimblerTable')
            #self.add(self.table)
            self.frame.add(self.table)
            
            # Set up the box to enter an app name
            self.enteredName = Gtk.Entry()
            self.table.attach(self.enteredName, 0, self.workspaces*2, self.max_windows+1, self.max_windows+2)
            self.enteredName.set_no_show_all(True)

            # Register enteredName event
            self.enteredName.connect('changed', self.enteredNameChanged)
            
            # Populate windows
            self.populate(self.windowList.get())
            
            # Set state
            self.hidden = False
            self.show_all()

            # Clear out the text field
            #self.enteredName.set_text('')
            #self.enteredName.grab_focus()

            # Show our window with focus
            self.stick()

            time = self.getXTime()

            self.get_window().focus(time)
        else:
            self.hidden = True
            self.table.destroy()
            self.hide()
            self.resize(1,1)

    def hotkey(self, key, data):
        self.toggle()

    def getXTime(self):
        try:
            time = GdkX11.x11_get_server_time(self.get_window())
        except:
            time = 0

        return time


class Config:

    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config.read([
            os.path.expanduser('~/.config/nimbler.conf'),
            os.path.expanduser('~/nimbler.conf'),
            os.path.expanduser('~/.nimbler.conf')
        ])

        self.loadOptions()

    def loadOptions(self):
        self.hotkey = self.getOption('hotkey', 'F10')
        self.ignored_windows = self.prepareIgnoredWindows(
            self.getOption('ignored_windows', [])
        )
        self.always_show_windows = self.prepareAlwaysShowWindows(
            self.getOption('always_show_windows', [])
        )
        self.ignored_window_types = self.getIgnoredWindowTypes()
        self.icon_size = self.get_icon_size(self.getOption('icon_size', 'default'))

    def getOption(self, option_name, default_value):
        if self.config.has_option('DEFAULT', option_name):
            return self.config.get('DEFAULT', option_name)
        else:
            return default_value

    def prepareIgnoredWindows(self, ignored_windows):
        return self.splitAndCompileWindowRegexes(ignored_windows)

    def prepareAlwaysShowWindows(self, always_show_windows):
        return self.splitAndCompileWindowRegexes(always_show_windows)

    def splitAndCompileWindowRegexes(self, windows):
        # Turn window str into a list
        if type(windows) is str:
            windows = filter(None, windows.split("\n"))

        # Now, turn each of the window names into a regex pattern
        for i in range(0, len(windows)):
            windows[i] = re.compile(windows[i])

        return windows

    def getIgnoredWindowTypes(self):
        window_types = {
            'normal': {'window_type': Wnck.WindowType.NORMAL, 'default': True},
            'desktop': {'window_type': Wnck.WindowType.DESKTOP, 'default': False},
            'dock': {'window_type': Wnck.WindowType.DOCK, 'default': False},
            'dialog': {'window_type': Wnck.WindowType.DIALOG, 'default': False},
            'toolbar': {'window_type': Wnck.WindowType.TOOLBAR, 'default': False},
            'menu': {'window_type': Wnck.WindowType.MENU, 'default': False},
            'utility': {'window_type': Wnck.WindowType.UTILITY, 'default': False},
            'splashscreen': {'window_type': Wnck.WindowType.SPLASHSCREEN, 'default': False},
        }

        ignored_window_types = []

        for window_type in window_types:
            should_show = bool(int(self.getOption('show_windows_' + window_type, window_types[window_type]['default'])))
            if not should_show:
                ignored_window_types.append(window_types[window_type]['window_type'])

        return ignored_window_types
        
    def get_icon_size(self, icon_size):
        if icon_size == 'default' or icon_size == 'mini':
            return icon_size
        elif icon_size.isdigit():
            icon_size = int(icon_size)
            Wnck.set_default_icon_size(icon_size)
            return 'default'

# Catch SIGINT signal
signal.signal(signal.SIGINT, signal.SIG_DFL)

# Load the configuration with defaults
config = Config()

# Create the window and set attributes
win = NimblerWindow(config)
win.connect("delete-event", Gtk.main_quit)
win.set_position(Gtk.WindowPosition.CENTER)
win.set_keep_above(True)
win.set_skip_taskbar_hint(True)
win.set_decorated(False)

# Set the hotkey
Keybinder.init()
if not Keybinder.bind(config.hotkey, win.hotkey, None):
    print("Could not bind the hotkey:", config.hotkey)
    exit()

# The main loop
Gtk.main()
