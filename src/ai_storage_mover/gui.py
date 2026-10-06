"""A desktop setup window. All migration work runs off the UI thread."""
import os
from pathlib import Path
import queue
import shutil
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from .discovery import candidates, project_suggestions, scan_folder
from .model import CLEANUP_PHRASE, MigrationError, read_json
from .wizard import backups, cleanup, create_session, load_session, migrate


def size(value):
    for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
        if value < 1024 or unit == 'TB':
            return f'{value:,.1f} {unit}'
        value /= 1024


class Wizard:
    def __init__(self, root):
        self.root = root
        root.title('AI Storage Mover')
        root.geometry('1040x760')
        root.minsize(880, 690)
        root.configure(bg='#101822')
        self.projects, self.items, self.selected = [], [], set()
        self.destinations = {}
        self.storage = tk.StringVar()
        self.project_destination = tk.StringVar()
        self.tools_temp, self.claude_temp = tk.StringVar(), tk.StringVar()
        self.content_check, self.closed = tk.BooleanVar(), tk.BooleanVar()
        self.error = tk.StringVar()
        self.phrase, self.tested = tk.StringVar(), tk.BooleanVar()
        self.events, self.stop = queue.Queue(), threading.Event()
        self.busy, self.closing, self.session, self.page = False, False, None, 0
        self.started = None
        style = ttk.Style(root)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 11), background='#101822', foreground='#e5edf6')
        style.configure('TFrame', background='#101822')
        style.configure('TLabel', background='#101822', foreground='#e5edf6')
        style.configure('Title.TLabel', font=('Segoe UI', 22, 'bold'))
        style.configure('Heading.TLabel', font=('Segoe UI', 17, 'bold'))
        style.configure('Muted.TLabel', foreground='#b6c6d8', font=('Segoe UI', 10))
        style.configure('Error.TLabel', foreground='#ffaaa5')
        style.configure('TButton', padding=(15, 9), background='#25394b', foreground='#e5edf6')
        style.map('TButton', background=[('active', '#37556e'), ('disabled', '#192633')], foreground=[('disabled', '#869bad')])
        style.configure('Primary.TButton', background='#8fdbc6', foreground='#102820')
        style.map('Primary.TButton', background=[('active', '#b2eedf'), ('disabled', '#263c40')], foreground=[('disabled', '#869bad')])
        style.configure('Danger.TButton', background='#eab0a9', foreground='#381719')
        style.map('Danger.TButton', background=[('disabled', '#30272b')], foreground=[('disabled', '#869bad')])
        style.configure('TEntry', fieldbackground='#192633', foreground='#e5edf6', padding=8)
        style.map('TEntry', fieldbackground=[('readonly', '#192633')], foreground=[('readonly', '#e5edf6')])
        style.configure('TCheckbutton', padding=(0, 5), background='#101822', foreground='#e5edf6')
        style.map('TCheckbutton', background=[('active', '#101822')])
        style.configure('Treeview', background='#192633', fieldbackground='#192633', foreground='#e5edf6', rowheight=32, borderwidth=0)
        style.configure('Treeview.Heading', background='#25394b', foreground='#e5edf6', font=('Segoe UI', 10, 'bold'), padding=8)
        style.map('Treeview', background=[('selected', '#37556e')])
        style.configure('Horizontal.TProgressbar', troughcolor='#25394b', background='#8fdbc6', borderwidth=0)
        shell = ttk.Frame(root, padding=28)
        shell.pack(fill='both', expand=True)
        ttk.Label(shell, text='AI Storage Mover', style='Title.TLabel').pack(anchor='w')
        self.steps = ttk.Label(shell, style='Muted.TLabel', padding=(0, 14, 0, 18))
        self.steps.pack(anchor='w')
        self.footer = ttk.Frame(shell)
        self.footer.pack(side='bottom', fill='x')
        self.error_label = ttk.Label(shell, textvariable=self.error, style='Error.TLabel', wraplength=940)
        self.error_label.pack(side='bottom', anchor='w', fill='x', pady=(10, 10))
        self.body = ttk.Frame(shell)
        self.body.pack(fill='both', expand=True)
        root.bind('<Configure>', lambda event: root.after_idle(self.fit_labels) if event.widget == root else None)
        root.protocol('WM_DELETE_WINDOW', self.close)
        self.show(0)
        root.after(150, self.poll)

    def clear(self, title, *, steps=True):
        self.error.set('')
        for frame in (self.body, self.footer):
            for widget in frame.winfo_children():
                widget.destroy()
        names = ['Projects', 'Destination', 'Data & temp', 'Review']
        self.steps.configure(text='   /   '.join(('[' + name + ']') if i == self.page else name for i, name in enumerate(names)) if steps else '')
        ttk.Label(self.body, text=title, style='Heading.TLabel').pack(anchor='w', pady=(0, 18))
        self.root.after_idle(self.fit_labels)

    def fit_labels(self):
        width = max(200, self.body.winfo_width() - 4)
        self.error_label.configure(wraplength=width)
        def visit(parent):
            for child in parent.winfo_children():
                if isinstance(child, ttk.Label) and int(child.cget('wraplength') or 0):
                    child.configure(wraplength=width)
                visit(child)
        visit(self.body)

    def button(self, parent, text, command, *, primary=False, side='left', **kw):
        widget = ttk.Button(parent, text=text, command=command, style='Primary.TButton' if primary else 'TButton', **kw)
        widget.pack(side=side, padx=(0, 10))
        return widget

    def table(self, parent, columns, headings, *, height=8, widths=None):
        frame = ttk.Frame(parent)
        frame.pack(fill='both', expand=True)
        view = ttk.Treeview(frame, columns=columns, show='headings', height=height, selectmode='extended')
        for i, (col, heading) in enumerate(zip(columns, headings)):
            view.heading(col, text=heading, anchor='w')
            view.column(col, width=widths[i] if widths else 200, minwidth=70, anchor='w')
        scroll = ttk.Scrollbar(frame, orient='vertical', command=view.yview)
        horizontal = ttk.Scrollbar(frame, orient='horizontal', command=view.xview)
        view.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        view.grid(row=0, column=0, sticky='nsew')
        scroll.grid(row=0, column=1, sticky='ns')
        horizontal.grid(row=1, column=0, sticky='ew')
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        return view

    def field(self, parent, label, variable, command):
        frame = ttk.Frame(parent)
        frame.pack(fill='x', pady=(10, 0))
        ttk.Label(frame, text=label).pack(anchor='w', pady=(0, 6))
        row = ttk.Frame(frame)
        row.pack(fill='x')
        ttk.Entry(row, textvariable=variable, state='readonly').pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Choose folder', command=command).pack(side='right', padx=(12, 0))

    def show(self, page):
        self.page = page
        if page == 0:
            self.clear('Choose your projects')
            ttk.Label(self.body, text='Use at your own risk. Make a separate manual backup before starting. File corruption or target-drive failure can cause data loss.',
                      style='Muted.TLabel', wraplength=930).pack(anchor='w', pady=(0, 16))
            self.project_list = self.table(self.body, ('name', 'path'), ('Folder', 'Current location'), widths=(190, 690))
            self.fill_projects()
            tools = ttk.Frame(self.body)
            tools.pack(fill='x', pady=(16, 0))
            self.button(tools, 'Add folder', self.add_project)
            self.button(tools, 'Remove selected', self.remove_projects)
            self.button(tools, 'Find existing projects', self.find_projects)
            self.button(tools, 'Scan a folder', lambda: self.scan('project'))
            self.button(self.footer, 'Open saved migration', self.open_saved)
            if self.recent_file().is_file():
                self.button(self.footer, 'Resume last migration', lambda: self.open_saved(recent=True))
        elif page == 1:
            self.clear('Choose the new location')
            self.field(self.body, 'AI storage folder', self.storage, self.choose_storage)
            self.field(self.body, 'Projects and new project default', self.project_destination, lambda: self.choose(self.project_destination))
            self.free = ttk.Label(self.body, style='Muted.TLabel')
            self.free.pack(anchor='w', pady=(16, 24))
            self.show_space()
            drives = ttk.Frame(self.body)
            drives.pack(anchor='w')
            if os.name == 'nt':
                for letter in 'DEFGHIJKLMNOPQRSTUVWXYZ':
                    drive = Path(letter + ':/')
                    if drive.exists():
                        try:
                            free = size(shutil.disk_usage(drive).free)
                            self.button(drives, letter + ':  ' + free + ' free', lambda p=drive: self.set_storage(p / 'AI'))
                        except OSError:
                            pass
            targets = ttk.Frame(self.body)
            targets.pack(fill='x', pady=(12, 6))
            ttk.Label(targets, text='Project destinations', style='Muted.TLabel').pack(side='left')
            self.button(targets, 'Change selected destination', self.change_destination, side='right')
            self.destination_list = self.table(self.body, ('source', 'target'), ('Project', 'New location'), height=2, widths=(190, 690))
            self.fill_destinations()
        elif page == 2:
            self.clear('Select profiles, caches and temp')
            if not self.items:
                self.items = candidates()
                used = set()
                for i, item in enumerate(self.items):
                    if item['slot'] not in used and Path(item['source']).resolve() != (Path(self.storage.get()) / item['slot']).resolve():
                        self.selected.add(i)
                        used.add(item['slot'])
            self.data_list = self.table(self.body, ('use', 'label', 'source'), ('Copy', 'Detected data', 'Current location'), height=4, widths=(70, 200, 610))
            self.fill_data()
            self.data_list.bind('<Button-1>', self.toggle_click)
            self.data_list.bind('<space>', lambda e: self.toggle_data())
            row = ttk.Frame(self.body)
            row.pack(fill='x', pady=(12, 0))
            self.button(row, 'Select / deselect', self.toggle_data)
            self.button(row, 'Add data folder', self.add_data)
            self.button(row, 'Add custom temp', self.add_temp)
            self.button(row, 'Find temp folders', lambda: self.scan('temp'))
            self.field(self.body, 'Future tool / build temp', self.tools_temp, lambda: self.choose(self.tools_temp))
            self.field(self.body, 'Future Claude temp', self.claude_temp, lambda: self.choose(self.claude_temp))
        elif page == 3:
            try:
                self.session = create_session(self.projects, self.storage.get(),
                    [self.items[i] for i in sorted(self.selected)], tools_temp=self.tools_temp.get(),
                    claude_temp=self.claude_temp.get(), projects_destination=self.project_destination.get(),
                    destinations=self.destinations,
                    verify_contents=self.content_check.get())
            except (MigrationError, OSError, ValueError) as exc:
                self.show(2)
                self.error.set(str(exc))
                return
            self.clear('Review the transfer')
            view = self.table(self.body, ('source', 'destination'), ('Current location', 'New location'), height=4, widths=(450, 450))
            for i, entry in enumerate(self.session['plan']['roots']):
                view.insert('', 'end', iid=str(i), values=(entry['source'], entry['destination']))
            details = tk.StringVar()
            ttk.Label(self.body, textvariable=details, style='Muted.TLabel', wraplength=930).pack(anchor='w', pady=(8, 0))
            def select_path(event=None):
                if view.selection():
                    entry = self.session['plan']['roots'][int(view.selection()[0])]
                    details.set('From: ' + entry['source'] + '\nTo: ' + entry['destination'])
            view.bind('<<TreeviewSelect>>', select_path)
            view.selection_set('0')
            select_path()
            ttk.Label(self.body, text='Fast copy. Original files stay on the old drive.', style='Muted.TLabel').pack(anchor='w', pady=(16, 4))
            ttk.Label(self.body, text='Fast checks use file size and date. Contents are checked before permanent cleanup.', style='Muted.TLabel').pack(anchor='w')
            ttk.Checkbutton(self.body, text='Verify file contents during transfer (slower)', variable=self.content_check).pack(anchor='w', pady=(8, 0))
            ttk.Checkbutton(self.body, text='I have closed apps and terminals using these folders.', variable=self.closed).pack(anchor='w')
        if page > 0:
            self.button(self.footer, 'Back', lambda: self.show(page - 1))
        self.button(self.footer, 'Start transfer' if page == 3 else 'Continue', self.next, primary=True, side='right')

    def choose(self, variable):
        folder = filedialog.askdirectory(parent=self.root, initialdir=variable.get() or None)
        if folder:
            variable.set(str(Path(folder).resolve()))
            if variable is self.project_destination:
                self.fill_destinations()

    def choose_storage(self):
        folder = filedialog.askdirectory(parent=self.root, title='Choose the AI storage folder')
        if folder:
            self.set_storage(Path(folder))

    def set_storage(self, folder):
        self.storage.set(str(Path(folder).resolve()))
        self.project_destination.set(str(Path(folder) / 'Projects'))
        self.tools_temp.set(str(Path(folder) / 'Temp' / 'tools'))
        self.claude_temp.set(str(Path(folder) / 'Temp' / 'claude'))
        self.destinations.clear()
        self.fill_destinations()
        self.show_space()

    def fill_destinations(self):
        if not hasattr(self, 'destination_list') or not self.destination_list.winfo_exists():
            return
        self.destination_list.delete(*self.destination_list.get_children())
        for i, path in enumerate(self.projects):
            target = self.destinations.get(path, str(Path(self.project_destination.get()) / Path(path).name))
            self.destination_list.insert('', 'end', iid=str(i), values=(Path(path).name, target))

    def change_destination(self):
        if not self.destination_list.selection():
            self.error.set('Select a project in the list first.')
            return
        raw = self.destination_list.selection()[0]
        source = self.projects[int(raw)]
        folder = filedialog.askdirectory(parent=self.root, title='Choose the exact destination folder for ' + Path(source).name,
                                         initialdir=self.project_destination.get() or None)
        if folder:
            self.destinations[source] = str(Path(folder).resolve())
            self.fill_destinations()

    def show_space(self):
        if hasattr(self, 'free') and self.free.winfo_exists() and self.storage.get():
            path = Path(self.storage.get())
            while not path.exists():
                path = path.parent
            try:
                self.free.configure(text=size(shutil.disk_usage(path).free) + ' available')
            except OSError:
                self.free.configure(text='Storage is unavailable')

    def fill_projects(self):
        self.project_list.delete(*self.project_list.get_children())
        for i, path in enumerate(self.projects):
            self.project_list.insert('', 'end', iid=str(i), values=(Path(path).name, path))

    def add_project(self):
        folder = filedialog.askdirectory(parent=self.root, title='Choose a project or a folder containing projects')
        if folder:
            path = str(Path(folder).resolve())
            if path not in self.projects:
                self.projects.append(path)
                self.fill_projects()

    def remove_projects(self):
        selected = {int(i) for i in self.project_list.selection()}
        self.projects = [p for i, p in enumerate(self.projects) if i not in selected]
        self.fill_projects()

    def find_projects(self):
        self.search(lambda: {'projects': project_suggestions()}, 'project')

    def scan(self, category):
        folder = filedialog.askdirectory(parent=self.root, title='Choose where to look')
        if folder:
            self.search(lambda: scan_folder(folder), category)

    def search(self, operation, category):
        if self.busy:
            return
        self.busy = True
        self.error.set('Looking for folders…')
        def work():
            try:
                self.events.put(('search', (operation(), category)))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=False).start()

    def choose_results(self, paths, category, limited=False):
        if not paths:
            self.error.set('No matching folders found. Use Add folder to select one.' + (' The bounded scan reached its limit.' if limited else ''))
            return
        dialog = tk.Toplevel(self.root)
        dialog.title('Select matching folders')
        dialog.geometry('860x450')
        dialog.configure(bg='#101822')
        dialog.transient(self.root)
        content = ttk.Frame(dialog, padding=24)
        content.pack(fill='both', expand=True)
        ttk.Label(content, text='Select the folders to include', style='Heading.TLabel').pack(anchor='w', pady=(0, 14))
        view = self.table(content, ('path',), ('Detected location',), widths=(750,))
        for i, path in enumerate(paths):
            view.insert('', 'end', iid=str(i), values=(path,))
        row = ttk.Frame(content)
        row.pack(fill='x', pady=(16, 0))
        def add():
            for i in view.selection():
                path = paths[int(i)]
                if category == 'project' and path not in self.projects:
                    self.projects.append(path)
                elif category == 'temp':
                    self.include_temp(path)
            dialog.destroy()
            self.show(self.page)
        self.button(row, 'Cancel', dialog.destroy)
        self.button(row, 'Add selected', add, primary=True, side='right')
        if limited:
            ttk.Label(content, text='Scan limited to 3 levels / 5,000 entries. Choose a smaller folder for more results.', style='Muted.TLabel').pack(anchor='w', pady=8)

    def fill_data(self):
        self.data_list.delete(*self.data_list.get_children())
        for i, item in enumerate(self.items):
            self.data_list.insert('', 'end', iid=str(i), values=('Yes' if i in self.selected else '', item['label'], item['source']))

    def toggle_click(self, event):
        row = self.data_list.identify_row(event.y)
        if row and self.data_list.identify_column(event.x) == '#1':
            self.data_list.selection_set(row)
            self.toggle_data()
            return 'break'

    def toggle_data(self):
        for raw in self.data_list.selection():
            i = int(raw)
            if i in self.selected:
                self.selected.remove(i)
            else:
                self.selected = {j for j in self.selected if self.items[j]['slot'] != self.items[i]['slot']}
                self.selected.add(i)
        self.fill_data()

    def include_temp(self, path):
        path = str(Path(path).resolve())
        if not any(i['source'] == path for i in self.items):
            self.items.append(dict(label='Custom temp', source=path, category='temp', slot='Temp/Imported/' + Path(path).name))
            self.selected.add(len(self.items) - 1)

    def add_temp(self):
        folder = filedialog.askdirectory(parent=self.root, title='Choose a dedicated AI or build temp folder')
        if folder:
            self.include_temp(folder)
            self.fill_data()

    def add_data(self):
        folder = filedialog.askdirectory(parent=self.root, title='Choose another app profile, cache or data folder')
        if folder:
            path = str(Path(folder).resolve())
            if not any(i['source'] == path for i in self.items):
                self.items.append(dict(label='Custom data', source=path, category='custom', slot='Data/' + Path(path).name))
                self.selected.add(len(self.items) - 1)
                self.fill_data()

    def next(self):
        if self.busy:
            return
        if self.page == 0 and not self.projects:
            self.error.set('Select at least one project folder.')
            return
        if self.page == 1 and not self.storage.get():
            self.error.set('Choose a destination folder.')
            return
        if self.page == 3:
            if not self.closed.get():
                self.error.set('Close the apps and terminals, then check the box above.')
                return
            # Rebuild the reviewed plan if the optional content check changed.
            self.session['plan']['verification'] = 'hash' if self.content_check.get() else 'metadata'
            self.start('transfer')
        else:
            self.show(self.page + 1)

    def start(self, action):
        self.action = action
        self.busy, self.closing = True, False
        self.stop.clear()
        self.started = time.monotonic()
        self.remember()
        phrase, tested = self.phrase.get(), self.tested.get()
        self.clear('Removing old copies' if action == 'cleanup' else 'Moving your storage', steps=False)
        self.detail = ttk.Label(self.body, text='Checking apps and folders…', wraplength=930)
        self.detail.pack(anchor='w', pady=(8, 24))
        self.progress = ttk.Progressbar(self.body, maximum=100)
        self.progress.pack(fill='x')
        self.count = ttk.Label(self.body, style='Muted.TLabel')
        self.count.pack(anchor='w', pady=(12, 8))
        self.elapsed = ttk.Label(self.body, style='Muted.TLabel')
        self.elapsed.pack(anchor='w')
        if action == 'transfer':
            ttk.Label(self.body, text='Originals are retained on the old drive.', style='Muted.TLabel').pack(anchor='w', pady=24)
        self.stop_button = self.button(self.footer, 'Stop safely', self.request_stop)
        self.button(self.footer, 'Open details', self.open_details, side='right')
        def work():
            try:
                if action == 'cleanup':
                    cleanup(self.session, phrase, tested=tested, cancelled=self.stop.is_set)
                else:
                    migrate(self.session, cancelled=self.stop.is_set)
                self.events.put(('finished', None))
            except Exception as exc:
                self.events.put(('error', str(exc)))
        threading.Thread(target=work, daemon=False).start()

    def request_stop(self):
        self.stop.set()
        if hasattr(self, 'stop_button') and self.stop_button.winfo_exists():
            self.stop_button.configure(state='disabled', text='Stopping after current file…')

    def poll(self):
        try:
            while True:
                kind, data = self.events.get_nowait()
                self.busy = False
                if self.closing:
                    self.root.destroy()
                    return
                if kind == 'search':
                    result, category = data
                    self.error.set('')
                    self.choose_results(result.get('projects' if category == 'project' else 'temps', []), category, result.get('limited', False))
                elif kind == 'finished':
                    if self.closing:
                        self.root.destroy()
                        return
                    self.finished()
                elif kind == 'error':
                    if self.closing:
                        self.root.destroy()
                        return
                    if hasattr(self, 'action') and self.session:
                        self.failed(data)
                    else:
                        self.error.set(data)
        except queue.Empty:
            pass
        if self.busy and self.session and hasattr(self, 'progress') and self.progress.winfo_exists():
            try:
                value = read_json(Path(self.session['plan']['run_dir']) / 'status.json')
                self.progress['value'] = value.get('percent', 0)
                self.detail.configure(text=value.get('detail', 'Working…'))
                count, total = value.get('done', 0), value.get('total')
                if value.get('phase') == 'native-copy' and value.get('transfer_bytes') is not None:
                    self.count.configure(text=size(value['transfer_bytes']) + ' written by Windows copy')
                else:
                    self.count.configure(text=f'{count:,} entries checked' if total is None else f'{count:,} / {total:,} entries')
            except (OSError, ValueError):
                pass
            if self.started:
                elapsed = int(time.monotonic() - self.started)
                self.elapsed.configure(text=f'Elapsed {elapsed // 60:02d}:{elapsed % 60:02d}')
        self.root.after(250, self.poll)

    def open_path(self, path):
        path = Path(path)
        if os.name == 'nt':
            os.startfile(str(path))
        else:
            import subprocess
            subprocess.Popen(['open' if sys.platform == 'darwin' else 'xdg-open', str(path)])

    def open_details(self):
        if self.session:
            self.open_path(self.session['plan']['run_dir'])

    def finished(self):
        cleaned = self.session.get('status') == 'cleaned'
        self.clear('Old copies removed' if cleaned else 'Migration complete', steps=False)
        ttk.Label(self.body, text='Original copies are retained on the old drive.' if not cleaned else 'Your projects and tool data are at the new location.').pack(anchor='w', pady=(0, 20))
        ttk.Label(self.body, text='Reopen apps and terminal tabs from the new launchers to use the new locations.', style='Muted.TLabel', wraplength=920).pack(anchor='w', pady=(0, 14))
        view = self.table(self.body, ('new',), ('New location',), widths=(880,))
        for entry in self.session['plan']['roots']:
            view.insert('', 'end', values=(entry['destination'],))
        row = ttk.Frame(self.body)
        row.pack(fill='x', pady=(18, 0))
        self.button(row, 'Open new projects', lambda: self.open_path(self.session['projects']))
        if not cleaned:
            self.button(row, 'View original copies', self.old_copies)
            self.button(row, 'Remove old copies…', self.cleanup_screen)
        self.button(self.footer, 'Close', self.close, primary=True, side='right')
        self.button(self.footer, 'Open migration record', self.open_details)
        self.remember()

    def recent_file(self):
        base = Path(sys.executable).parent if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2] / '.runs'
        return base / 'recent-migration.local.json'

    def remember(self):
        from .model import atomic_json
        try:
            atomic_json(self.recent_file(), {'session': str(Path(self.session['plan']['run_dir']) / 'wizard.local.json')})
        except OSError:
            pass

    def old_copies(self):
        self.clear('Original copies on the old drive', steps=False)
        ttk.Label(self.body, text='These physical backup folders can be kept or removed manually. The old project paths now link to the new drive.', style='Muted.TLabel', wraplength=920).pack(anchor='w', pady=(0, 14))
        view = self.table(self.body, ('path',), ('Retained original folder',), widths=(880,))
        for i, path in enumerate(backups(self.session)):
            view.insert('', 'end', iid=str(i), values=(path,))
        view.bind('<Double-1>', lambda e: self.open_path(backups(self.session)[int(view.selection()[0])]) if view.selection() else None)
        self.button(self.footer, 'Back', self.finished)
        self.button(self.footer, 'Open selected folder', lambda: self.open_path(backups(self.session)[int(view.selection()[0])]) if view.selection() else None, side='right')

    def cleanup_screen(self):
        self.phrase.set('')
        self.tested.set(False)
        self.clear('Permanently remove the old copies', steps=False)
        ttk.Label(self.body, text='Every old project, profile, cache and temp copy listed below will be deleted from the old drive. No undo or Recycle Bin. Your new copies stay.', wraplength=920).pack(anchor='w', pady=(0, 14))
        view = self.table(self.body, ('path',), ('Old copy to delete',), height=4, widths=(880,))
        for path in backups(self.session):
            view.insert('', 'end', values=(path,))
        ttk.Checkbutton(self.body, text='I have opened and checked my projects at the new location.', variable=self.tested,
                        command=self.enable_cleanup).pack(anchor='w', pady=(14, 8))
        ttk.Label(self.body, text='Type this exact phrase:', style='Muted.TLabel').pack(anchor='w')
        ttk.Label(self.body, text=CLEANUP_PHRASE, font=('Segoe UI', 11, 'bold'), wraplength=920).pack(anchor='w', pady=(6, 10))
        self.phrase_entry = ttk.Entry(self.body, textvariable=self.phrase)
        self.phrase_entry.pack(fill='x')
        self.phrase_entry.bind('<KeyRelease>', lambda e: self.enable_cleanup())
        self.button(self.footer, 'Keep originals', self.finished)
        self.delete_button = ttk.Button(self.footer, text='Delete old copies permanently', style='Danger.TButton',
                                       command=self.confirm_cleanup, state='disabled')
        self.delete_button.pack(side='right')

    def enable_cleanup(self):
        if hasattr(self, 'delete_button') and self.delete_button.winfo_exists():
            self.delete_button.configure(state='normal' if self.phrase.get() == CLEANUP_PHRASE and self.tested.get() else 'disabled')

    def confirm_cleanup(self):
        if self.phrase.get() != CLEANUP_PHRASE or not self.tested.get():
            return
        self.start('cleanup')

    def failed(self, detail):
        self.clear('Setup stopped' if self.action == 'transfer' else 'Cleanup stopped', steps=False)
        ttk.Label(self.body, text=detail, wraplength=920, style='Error.TLabel').pack(anchor='w', pady=(0, 18))
        self.button(self.footer, 'Retry transfer' if self.action == 'transfer' else 'Review cleanup',
                    lambda: self.start('transfer') if self.action == 'transfer' else self.cleanup_screen(), primary=True, side='right')
        self.button(self.footer, 'Open error details', self.open_details)
        self.button(self.footer, 'Close', self.close)

    def open_saved(self, recent=False):
        initial = None
        try:
            saved = read_json(self.recent_file())
            path = Path(saved['session'])
            if recent and path.is_file():
                self.session = load_session(path)
                if self.session['status'] in ('complete', 'cleaned'):
                    self.finished()
                else:
                    self.action = 'transfer'
                    self.failed('The saved transfer can be resumed. Close its apps and terminals, then choose Retry.')
                return
            initial = str(path.parent)
        except (OSError, ValueError, KeyError, MigrationError):
            pass
        file = filedialog.askopenfilename(parent=self.root, title='Open a saved migration',
                                         initialdir=initial, filetypes=[('Saved setup', 'wizard.local.json plan.local.json'), ('JSON files', '*.json')])
        if file:
            try:
                self.session = load_session(file)
                if self.session['status'] in ('complete', 'cleaned'):
                    self.finished()
                else:
                    self.action = 'transfer'
                    self.failed('The saved transfer can be resumed. Close its apps and terminals, then choose Retry.')
            except (OSError, ValueError, MigrationError) as exc:
                self.error.set(str(exc))

    def close(self):
        if self.busy:
            detail = ('Stop after the current file and close? Completed cleanup deletions cannot be undone.'
                      if getattr(self, 'action', None) == 'cleanup' else 'Stop after the current file and close? Original copies will be retained.')
            if messagebox.askyesno('Stop safely?', detail, parent=self.root):
                self.closing = True
                self.request_stop()
        else:
            self.root.destroy()


def main():
    root = tk.Tk()
    Wizard(root)
    root.mainloop()
    return 0
