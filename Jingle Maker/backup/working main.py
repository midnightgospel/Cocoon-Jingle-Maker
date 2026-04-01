import customtkinter as ctk
from tkinter import filedialog, messagebox
import yt_dlp
import os
import pygame
import threading
import subprocess
import hashlib

class JingleMaker(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Jingle Maker Pro - Library Manager")
        # Start at the smallest functional size
        self.geometry("700x750")
        self.minsize(700, 750)
        ctk.set_appearance_mode("dark")

        # Audio Settings
        pygame.mixer.init()
        
        # State
        self.current_playing_button = None
        self.is_downloading = False
        self.game_queue = []
        self.total_in_queue = 0
        self.current_game_path = ""
        self.target_extensions = ('.gba', '.nds', '.sfc', '.nes', '.zip', '.gb', '.gbc', '.3ds', '.n64', '.v64', '.z64', '.iso')

        # UI Construction
        self.main_frame = ctk.CTkFrame(self, corner_radius=15)
        self.main_frame.pack(pady=20, padx=20, fill="both", expand=True)

        # Title using Textbox to prevent descender clipping (g, j, y)
        self.title_box = ctk.CTkTextbox(self.main_frame, height=50, width=240, font=("Arial", 28, "bold"), 
                                       fg_color="transparent", border_width=0, activate_scrollbars=False)
        self.title_box.insert("0.0", "Jingle Maker Pro")
        self.title_box.configure(state="disabled")
        self.title_box.pack(pady=(20, 5))

        self.bulk_frame = ctk.CTkFrame(self.main_frame, fg_color="#2c3e50")
        self.bulk_frame.pack(pady=10, padx=20, fill="x")
        
        # Reverted to Green with Darker Hover
        self.bulk_btn = ctk.CTkButton(
            self.bulk_frame, 
            text="📁 Select Root Games Folder", 
            command=self.show_folder_picker, 
            fg_color="#16a085",
            hover_color="#148f77"
        )
        self.bulk_btn.pack(side="left", padx=10, pady=10)
        
        self.queue_label = ctk.CTkLabel(self.bulk_frame, text="No folder selected", font=("Arial", 12, "italic"))
        self.queue_label.pack(side="left", padx=10, fill="x", expand=True)

        # Search UI
        self.search_entry = ctk.CTkEntry(self.main_frame, width=420)
        self.search_entry.pack(pady=5, fill="x", padx=100)
        self.search_entry.bind("<Return>", lambda e: self.search_youtube(self.search_entry.get()))
        
        self.btn_row = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.btn_row.pack(pady=5)

        self.search_btn = ctk.CTkButton(self.btn_row, text="Search", command=lambda: self.search_youtube(self.search_entry.get()), width=150)
        self.search_btn.pack(side="left", padx=5)

        self.skip_btn = ctk.CTkButton(self.btn_row, text="Skip Game ⏭", command=self.next_game, width=150, fg_color="#7f8c8d", hover_color="#5f6a6a")
        self.skip_btn.pack(side="left", padx=5)

        self.results_frame = ctk.CTkScrollableFrame(self.main_frame, label_text="Results")
        self.results_frame.pack(pady=10, padx=10, fill="both", expand=True)

        # Progress Section
        self.progress_frame = ctk.CTkFrame(self.main_frame, fg_color="transparent")
        self.progress_frame.pack(fill="x", padx=40, pady=(10, 0))
        
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame)
        self.progress_bar.set(0)
        self.progress_bar.pack(pady=5, fill="x")
        
        self.progress_text = ctk.CTkLabel(self.progress_frame, text="Progress: 0/0", font=("Arial", 11))
        self.progress_text.pack()

        self.status_label = ctk.CTkLabel(self.main_frame, text="Ready", font=("Arial", 13))
        self.status_label.pack(pady=10)

        self.protocol("WM_DELETE_WINDOW", self.on_closing)

    def show_folder_picker(self):
        root_dir = filedialog.askdirectory()
        self.focus_set()
        
        if not root_dir: return

        valid_subfolders = []
        for root, dirs, files in os.walk(root_dir):
            if any(f.lower().endswith(self.target_extensions) for f in files):
                valid_subfolders.append(root)

        if not valid_subfolders:
            messagebox.showinfo("No Games", "No supported game files found.")
            return

        self.picker = ctk.CTkToplevel(self)
        self.picker.title("Select Folders")
        self.picker.geometry("600x500")
        self.picker.grab_set()

        scroll = ctk.CTkScrollableFrame(self.picker)
        scroll.pack(pady=20, padx=20, fill="both", expand=True)

        checkboxes = []
        all_var = ctk.BooleanVar(value=True)
        def toggle_all():
            for _, var in checkboxes: var.set(all_var.get())
        
        ctk.CTkCheckBox(scroll, text="SELECT ALL", variable=all_var, command=toggle_all, font=("Arial", 12, "bold")).pack(anchor="w", pady=5)

        for path in valid_subfolders:
            var = ctk.BooleanVar(value=True)
            display_name = os.path.relpath(path, root_dir)
            cb = ctk.CTkCheckBox(scroll, text=display_name if display_name != "." else "Root Folder", variable=var)
            cb.pack(anchor="w", pady=2)
            checkboxes.append((path, var))

        def confirm():
            self.game_queue = []
            for path, var in checkboxes:
                if var.get():
                    for f in os.listdir(path):
                        if f.lower().endswith(self.target_extensions):
                            self.game_queue.append(os.path.join(path, f))
            
            self.total_in_queue = len(self.game_queue)
            self.update_progress_ui()
            self.picker.destroy()
            if self.game_queue:
                self.next_game()

        ctk.CTkButton(self.picker, text="Start Processing", command=confirm).pack(pady=10)

    def update_progress_ui(self):
        if self.total_in_queue > 0:
            completed = self.total_in_queue - len(self.game_queue)
            percent = completed / self.total_in_queue
            self.progress_bar.set(percent)
            self.progress_text.configure(text=f"Progress: {completed}/{self.total_in_queue}")
        else:
            self.progress_bar.set(0)
            self.progress_text.configure(text="Progress: 0/0")

    def next_game(self):
        self.stop_audio()
        self.clear_preview_cache()
        self.update_progress_ui()
        
        if not self.game_queue:
            self.status_label.configure(text="✅ All games processed!", text_color="#2ecc71")
            return

        self.current_game_path = self.game_queue.pop(0)
        base = os.path.splitext(os.path.basename(self.current_game_path))[0]
        jingle_path = os.path.join(os.path.dirname(self.current_game_path), f"{base} - Jingle.ogg")

        if os.path.exists(jingle_path):
            self.show_conflict_dialog(base)
            return

        self.trigger_search(base)

    def show_conflict_dialog(self, base_name):
        dialog = ctk.CTkToplevel(self)
        dialog.title("Conflict")
        dialog.geometry("400x180")
        dialog.grab_set()
        dialog.resizable(False, False)
        
        lbl = ctk.CTkLabel(dialog, text=f"'{base_name}'\nalready has a jingle.", font=("Arial", 14))
        lbl.pack(pady=20)

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=10)

        def select(choice):
            dialog.destroy()
            if choice == "replace": self.trigger_search(base_name)
            elif choice == "skip": self.next_game()
            elif choice == "stop": 
                self.game_queue = []
                self.update_progress_ui()

        ctk.CTkButton(btn_frame, text="Replace", width=90, command=lambda: select("replace")).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Skip", width=90, fg_color="#7f8c8d", hover_color="#5f6a6a", command=lambda: select("skip")).pack(side="left", padx=5)
        ctk.CTkButton(btn_frame, text="Stop", width=90, fg_color="#c0392b", hover_color="#922b21", command=lambda: select("stop")).pack(side="left", padx=5)

    def trigger_search(self, base):
        clean_name = base.split('(')[0].split('[')[0].strip()
        query = f"{clean_name} theme song"
        self.queue_label.configure(text=f"Current: {clean_name}")
        self.search_entry.delete(0, 'end')
        self.search_entry.insert(0, query)
        self.search_youtube(query)

    def search_youtube(self, query):
        if not query: return
        self.stop_audio()
        self.status_label.configure(text="Searching...", text_color="#3498db")
        for widget in self.results_frame.winfo_children(): widget.destroy()

        def search_thread():
            search_opts = {
                'quiet': True,
                'no_warnings': True,
                'js_runtimes': {'node': {}},
                'extractor_args': {'youtube': {'remote_components': ['ejs:github']}},
                'extract_flat': True,
                'match_filter': yt_dlp.utils.match_filter_func("duration < 1200"),
            }
            try:
                with yt_dlp.YoutubeDL(search_opts) as ydl:
                    result = ydl.extract_info(f"ytsearch20:{query}", download=False)
                    if 'entries' not in result or not result['entries']:
                        self.after(0, lambda: self.status_label.configure(text="No Results Found", text_color="yellow"))
                        return

                    valid_entries = [e for e in result['entries'] if e is not None][:10]

                    for entry in valid_entries:
                        video_data = {
                            'title': entry.get('title', 'Unknown Title'),
                            'url': entry.get('url') or entry.get('webpage_url')
                        }
                        self.after(0, self.create_result_row, video_data)
                self.after(0, lambda: self.status_label.configure(text="Ready", text_color="white"))
            except Exception as e:
                print(f"Search Error: {e}")
                self.after(0, lambda: self.status_label.configure(text="Search Error", text_color="red"))

        threading.Thread(target=search_thread, daemon=True).start()

    def create_result_row(self, data):
        row = ctk.CTkFrame(self.results_frame, fg_color="transparent")
        row.pack(fill="x", pady=2)
        
        p_btn = ctk.CTkButton(row, text="▶", width=40, fg_color="#27ae60", hover_color="#1e8449")
        p_btn.configure(command=lambda: self.toggle_preview(p_btn, data['url']))
        p_btn.pack(side="left", padx=2)
        
        ctk.CTkLabel(row, text=data['title'][:70], anchor="w").pack(side="left", fill="x", expand=True, padx=5)
        
        s_btn = ctk.CTkButton(row, text="Save & Next", width=100, fg_color="#2980b9", hover_color="#1f618d")
        s_btn.configure(command=lambda: self.manual_save(data))
        s_btn.pack(side="right", padx=2)

    def toggle_preview(self, button, url):
        if self.current_playing_button == button:
            if pygame.mixer.music.get_busy():
                self.stop_audio()
                return

        self.stop_audio()
        self.current_playing_button = button
        url_hash = hashlib.md5(url.encode()).hexdigest()
        cache_path = os.path.join(os.getcwd(), f"cache_{url_hash}.mp3")

        if os.path.exists(cache_path):
            self.play_existing(cache_path, button)
        else:
            button.configure(text="🔍", fg_color="#e67e22", hover_color="#b9651b")
            threading.Thread(target=self.check_size_and_download, args=(url, button, cache_path), daemon=True).start()

    def check_size_and_download(self, url, button, cache_path):
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'js_runtimes': {'node': {}}}) as ydl:
                info = ydl.extract_info(url, download=False)
                size_bytes = info.get('filesize') or info.get('filesize_approx') or 0
                size_mb = size_bytes / (1024 * 1024)

                if size_mb > 50:
                    msg = f"This preview is ~{size_mb:.1f} MB. Proceed?"
                    if not messagebox.askyesno("Large File Warning", msg):
                        self.after(0, self.stop_audio)
                        return

            self.after(0, lambda: button.configure(text="⏳"))
            self.download_and_play(url, button, cache_path)
        except:
            self.after(0, lambda: self.download_and_play(url, button, cache_path))

    def download_and_play(self, url, button, target_path):
        try:
            preview_opts = {
                'format': 'bestaudio/best',
                'outtmpl': target_path.replace('.mp3', ''),
                'quiet': True,
                'no_warnings': True,
                'js_runtimes': {'node': {}},
                'extractor_args': {'youtube': {'remote_components': ['ejs:github']}},
                'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'mp3'}]
            }
            with yt_dlp.YoutubeDL(preview_opts) as ydl:
                ydl.download([url])
            
            if os.path.exists(target_path):
                self.after(0, lambda: self.play_existing(target_path, button))
        except:
            self.after(0, self.stop_audio)

    def play_existing(self, path, button):
        try:
            pygame.mixer.music.load(path)
            pygame.mixer.music.play()
            button.configure(text="⏹", fg_color="#c0392b", hover_color="#922b21")
        except:
            self.stop_audio()

    def process_download(self, url, folder, filename):
        temp_raw = os.path.join(folder, f"{filename}_raw.opus")
        final_ogg = os.path.join(folder, f"{filename}.ogg")
        
        ydl_opts = {
            'format': 'bestaudio/best',
            'quiet': True,
            'no_warnings': True,
            'js_runtimes': {'node': {}},
            'extractor_args': {'youtube': {'remote_components': ['ejs:github']}},
            'outtmpl': os.path.join(folder, f"{filename}_raw"),
            'postprocessors': [{'key': 'FFmpegExtractAudio', 'preferredcodec': 'opus'}],
        }
        
        try:
            self.status_label.configure(text="Downloading...", text_color="#f1c40f")
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])
            
            if os.path.exists(temp_raw):
                self.status_label.configure(text="Mastering (30s Trim)...", text_color="#3498db")
                cmd = [
                    '/opt/homebrew/bin/ffmpeg', '-y', '-i', temp_raw,
                    '-t', '30',
                    '-af', 'loudnorm=I=-14:TP=-1.5:LRA=11, afade=t=out:st=28:d=2',
                    '-c:a', 'libopus', '-b:a', '128k', final_ogg
                ]
                subprocess.run(cmd, check=True, capture_output=True)
                os.remove(temp_raw)
            
            self.is_downloading = False
            self.after(0, self.next_game)
        except Exception as e:
            self.is_downloading = False
            print(f"Download Error: {e}")
            self.after(0, lambda: messagebox.showerror("Error", "Processing failed."))

    def manual_save(self, data):
        self.stop_audio()
        base_dir = os.path.dirname(self.current_game_path)
        base_name = os.path.splitext(os.path.basename(self.current_game_path))[0]
        final_filename = f"{base_name} - Jingle"
        self.is_downloading = True
        threading.Thread(target=self.process_download, args=(data['url'], base_dir, final_filename), daemon=True).start()

    def stop_audio(self):
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        if self.current_playing_button:
            self.current_playing_button.configure(
                text="▶", 
                fg_color="#27ae60", 
                hover_color="#1e8449"
            )
            self.current_playing_button = None

    def clear_preview_cache(self):
        for f in os.listdir(os.getcwd()):
            if f.startswith("cache_") and f.endswith(".mp3"):
                try:
                    os.remove(f)
                except: pass

    def on_closing(self):
        self.stop_audio()
        self.clear_preview_cache()
        self.destroy()

if __name__ == "__main__":
    app = JingleMaker()
    app.mainloop()