import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from thonny import get_runner, get_workbench
from thonny.plugins.ai_assistant.code_sanitizer import extract_code
from thonny.plugins.ai_assistant.config_manager import ConfigManager
from thonny.plugins.ai_assistant.hardware_context import detect_hardware
from thonny.plugins.ai_assistant.models import GenerationRequest
from thonny.plugins.ai_assistant.prompt_builder import build_messages
from thonny.plugins.ai_assistant.providers import CodexAccountProvider, PROFILES, OpenAICompatibleProvider, profile_for
from thonny.plugins.ai_assistant.providers.base import RequestCancelled
from thonny.plugins.ai_assistant.thonny_adapter import ThonnyAdapter


class AIAssistantView(ttk.Frame):
    """Chat-style MicroPython assistant using only Tk and the Python stdlib."""

    def __init__(self, master):
        super().__init__(master, padding=5)
        self.workbench, self.runner = get_workbench(), get_runner()
        self.config = ConfigManager(self.workbench)
        self.config.install_defaults()
        self.adapter = ThonnyAdapter(self.workbench, self.runner)
        self.adapter.subscribe(self._on_backend_event)
        self.history, self.last_assistant_text = [], ""
        self.events, self.cancel_event, self.worker = queue.Queue(), threading.Event(), None
        self.provider_id = tk.StringVar(value=self.config.get("provider"))
        self.model = tk.StringVar(value=self.config.get("model"))
        self.api_key = tk.StringVar()
        self.custom_url = tk.StringVar(value=self.config.get("custom_url"))
        self.write_editor = tk.BooleanVar(value=self.config.get("write_editor"))
        self.auto_run = tk.BooleanVar(value=self.config.get("auto_run"))
        self.auto_fix = tk.BooleanVar(value=self.config.get("auto_fix"))
        self.status_text, self.hardware_text = tk.StringVar(value="Ready"), tk.StringVar()
        self.account_text = tk.StringVar(value="Account status: unknown")
        self._build_ui()
        self._provider_changed()
        self.refresh_hardware()
        self.after(40, self._drain_events)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)
        config = ttk.LabelFrame(self, text="Model", padding=5)
        config.grid(row=0, column=0, sticky="ew")
        config.columnconfigure(1, weight=1)
        ttk.Label(config, text="Provider").grid(row=0, column=0, sticky="w")
        self.provider_combo = ttk.Combobox(config, textvariable=self.provider_id, state="readonly", values=[p.id for p in PROFILES])
        self.provider_combo.grid(row=0, column=1, sticky="ew", padx=(5, 0))
        self.provider_combo.bind("<<ComboboxSelected>>", lambda event: self._provider_changed())
        ttk.Label(config, text="Model").grid(row=1, column=0, sticky="w")
        self.model_combo = ttk.Combobox(config, textvariable=self.model)
        self.model_combo.grid(row=1, column=1, sticky="ew", padx=(5, 0))
        ttk.Label(config, text="API key").grid(row=2, column=0, sticky="w")
        self.key_entry = ttk.Entry(config, textvariable=self.api_key, show="•")
        self.key_entry.grid(row=2, column=1, sticky="ew", padx=(5, 0))
        ttk.Label(config, text="Custom URL").grid(row=3, column=0, sticky="w")
        self.url_entry = ttk.Entry(config, textvariable=self.custom_url)
        self.url_entry.grid(row=3, column=1, sticky="ew", padx=(5, 0))
        self.refresh_button = ttk.Button(config, text="Refresh models", command=self.refresh_models)
        self.refresh_button.grid(row=4, column=1, sticky="e", pady=(4, 0))
        self.account_frame = ttk.Frame(config)
        self.account_frame.grid(row=5, column=0, columnspan=2, sticky="e")
        self.account_label = ttk.Label(self.account_frame, textvariable=self.account_text)
        self.account_label.pack(side="top", fill="x", pady=(2, 3))
        account_buttons = ttk.Frame(self.account_frame)
        account_buttons.pack(side="top", anchor="e")
        self.sign_in_button = ttk.Button(account_buttons, text="Sign in", command=self.sign_in)
        self.sign_in_button.pack(side="left")
        self.status_button = ttk.Button(account_buttons, text="Status", command=self.account_status)
        self.status_button.pack(side="left", padx=3)
        self.sign_out_button = ttk.Button(account_buttons, text="Sign out", command=self.sign_out)
        self.sign_out_button.pack(side="left")
        context = ttk.Frame(self)
        context.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        ttk.Label(context, textvariable=self.hardware_text).pack(side="left", fill="x", expand=True)
        ttk.Button(context, text="↻", width=3, command=self.refresh_hardware).pack(side="right")
        self.chat = scrolledtext.ScrolledText(self, wrap="word", state="disabled", height=12)
        self.chat.grid(row=2, column=0, sticky="nsew")
        self.chat.tag_configure("user", foreground="#1769aa", spacing1=8)
        self.chat.tag_configure("assistant", foreground="#237a3b", spacing1=8)
        self.chat.tag_configure("error", foreground="#b3261e", spacing1=8)
        self.input = tk.Text(self, height=5, wrap="word", undo=True)
        self.input.grid(row=3, column=0, sticky="ew", pady=(5, 2))
        self.input.bind("<Control-Return>", self._send_event)
        self.input.bind("<Command-Return>", self._send_event)
        options = ttk.Frame(self)
        options.grid(row=4, column=0, sticky="ew")
        for label, var in (("Write to editor", self.write_editor), ("Auto-run", self.auto_run), ("Auto-fix", self.auto_fix)):
            ttk.Checkbutton(options, text=label, variable=var).pack(side="left")
        buttons = ttk.Frame(self)
        buttons.grid(row=5, column=0, sticky="ew", pady=(3, 0))
        self.send_button = ttk.Button(buttons, text="Send", command=self.send)
        self.send_button.pack(side="right")
        self.cancel_button = ttk.Button(buttons, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right", padx=4)
        ttk.Button(buttons, text="Write code", command=self.write_last_code).pack(side="right")
        ttk.Button(buttons, text="Clear", command=self.clear).pack(side="left")
        ttk.Label(self, textvariable=self.status_text).grid(row=6, column=0, sticky="w", pady=(3, 0))

    def _provider_changed(self):
        profile = profile_for(self.provider_id.get())
        self.model.set(profile.default_model)
        self.url_entry.configure(state="normal" if profile.id == "custom" else "disabled")
        self.key_entry.configure(state="disabled" if profile.id == "codex" else "normal")
        self.account_frame.grid() if profile.id == "codex" else self.account_frame.grid_remove()
        self.config.set("provider", profile.id)
        if profile.id == "codex": self.account_status(show_dialog=False)

    def _provider(self):
        profile = profile_for(self.provider_id.get())
        if profile.id == "codex": return CodexAccountProvider()
        base_url = self.custom_url.get().strip() if profile.id == "custom" else profile.base_url
        self.config.set_session_key(profile.id, self.api_key.get().strip())
        return OpenAICompatibleProvider(base_url, self.config.get_api_key(profile.id))

    def sign_in(self):
        try:
            provider = self._provider()
            process = provider.login()
            self._account_busy(True, "Waiting for browser sign-in…")
            threading.Thread(target=self._login_worker, args=(provider, process), daemon=True).start()
        except Exception as exc: messagebox.showerror("AI Assistant", str(exc), parent=self)

    def _login_worker(self, provider, process):
        try:
            logged_in, detail = provider.finish_login(process)
            self.events.put(("account", (logged_in, detail, True)))
        except Exception as exc:
            self.events.put(("account", (False, str(exc), True)))

    def sign_out(self):
        self._account_busy(True, "Signing out…")
        threading.Thread(target=self._logout_worker, args=(self._provider(),), daemon=True).start()

    def _logout_worker(self, provider):
        try:
            result = provider.logout()
            detail = (result.stdout + result.stderr).strip()
            self.events.put(("account", (False, detail or "Signed out", True)))
        except Exception as exc: self.events.put(("account", (False, str(exc), True)))

    def account_status(self, show_dialog=True):
        try:
            self._account_busy(True, "Checking account…")
            threading.Thread(target=self._status_worker, args=(self._provider(), show_dialog), daemon=True).start()
        except Exception as exc: messagebox.showerror("AI Assistant", str(exc), parent=self)

    def _status_worker(self, provider, show_dialog):
        try:
            logged_in, detail = provider.auth_status()
            self.events.put(("account", (logged_in, detail, show_dialog)))
        except Exception as exc: self.events.put(("account", (False, str(exc), show_dialog)))

    def _account_busy(self, busy, text=None):
        state = "disabled" if busy else "normal"
        for button in (self.sign_in_button, self.status_button, self.sign_out_button): button.configure(state=state)
        if text: self.account_text.set(text)

    def refresh_hardware(self):
        hardware = detect_hardware(self.workbench, self.runner)
        self.hardware_text.set("Target: " + (hardware.board if hardware.connected else "not connected"))
        return hardware

    def refresh_models(self):
        if self.worker and self.worker.is_alive(): return
        self._busy(True, "Fetching models…")
        self.worker = threading.Thread(target=self._models_worker, args=(self._provider(),), daemon=True)
        self.worker.start()

    def _models_worker(self, provider):
        try: self.events.put(("models", provider.list_models()))
        except Exception as exc: self.events.put(("error", str(exc)))
        finally: self.events.put(("idle", None))

    def _send_event(self, event):
        self.send()
        return "break"

    def send(self):
        prompt = self.input.get("1.0", "end-1c").strip()
        if not prompt or (self.worker and self.worker.is_alive()): return
        if not self.model.get().strip():
            messagebox.showerror("AI Assistant", "Select or enter a model first", parent=self); return
        self.input.delete("1.0", "end")
        self.history.append({"role": "user", "content": prompt})
        self._append_message("You", prompt, "user")
        self._append_message("Assistant", "", "assistant")
        self.last_assistant_text, self.cancel_event = "", threading.Event()
        request = GenerationRequest(self.model.get().strip(), build_messages(self.history, self.refresh_hardware()))
        self._save_preferences(); self._busy(True, "Generating…")
        self.worker = threading.Thread(target=self._generate_worker, args=(self._provider(), request, self.cancel_event), daemon=True)
        self.worker.start()

    def _generate_worker(self, provider, request, cancel):
        try:
            result = provider.generate(request, lambda delta: self.events.put(("delta", delta)), cancel)
            self.events.put(("complete", result.text))
        except RequestCancelled: self.events.put(("cancelled", None))
        except Exception as exc: self.events.put(("error", str(exc)))
        finally: self.events.put(("idle", None))

    def _drain_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "delta": self.last_assistant_text += value; self._append_raw(value, "assistant")
                elif kind == "complete":
                    self.last_assistant_text = value or self.last_assistant_text
                    self.history.append({"role": "assistant", "content": self.last_assistant_text})
                    if self.write_editor.get(): self.write_last_code(silent=True)
                elif kind == "models":
                    self.model_combo["values"] = value
                    if value and self.model.get() not in value: self.model.set(value[0])
                elif kind == "error": self._append_message("Error", value, "error")
                elif kind == "cancelled": self._append_message("System", "Request cancelled", "error")
                elif kind == "account":
                    logged_in, detail, show_dialog = value
                    label = "Signed in with ChatGPT" if logged_in else "Not signed in"
                    self.account_text.set(label)
                    self.account_label.configure(foreground="#237a3b" if logged_in else "#b3261e")
                    self._account_busy(False)
                    if show_dialog: messagebox.showinfo("OpenAI account", detail or label, parent=self)
                elif kind == "idle": self._busy(False, "Ready")
        except queue.Empty: pass
        if self.winfo_exists(): self.after(40, self._drain_events)

    def _append_message(self, label, text, tag):
        self.chat.configure(state="normal")
        if self.chat.index("end-1c") != "1.0": self.chat.insert("end", "\n")
        self.chat.insert("end", label + ":\n", tag); self.chat.insert("end", text + "\n", tag)
        self.chat.configure(state="disabled"); self.chat.see("end")

    def _append_raw(self, text, tag):
        self.chat.configure(state="normal"); self.chat.insert("end", text, tag)
        self.chat.configure(state="disabled"); self.chat.see("end")

    def write_last_code(self, silent=False):
        try:
            cleaned = extract_code(self.last_assistant_text)
            if cleaned.warnings:
                if silent: self.status_text.set("Code has warnings; review before writing"); return False
                if not messagebox.askyesno("AI Assistant", "\n".join(cleaned.warnings) + "\n\nWrite anyway?", parent=self): return False
            self.adapter.write_editor(cleaned.code)
            if self.auto_run.get(): self.adapter.execute_current()
            self.status_text.set("Code written to editor"); return True
        except Exception as exc:
            if silent: self.status_text.set(str(exc))
            else: messagebox.showerror("AI Assistant", str(exc), parent=self)
            return False

    def cancel(self): self.cancel_event.set(); self.status_text.set("Cancelling…")

    def clear(self):
        self.history.clear(); self.last_assistant_text = ""
        self.chat.configure(state="normal"); self.chat.delete("1.0", "end"); self.chat.configure(state="disabled")

    def _busy(self, busy, text):
        self.status_text.set(text)
        self.send_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.refresh_button.configure(state="disabled" if busy else "normal")

    def _save_preferences(self):
        for name, value in (("provider", self.provider_id.get()), ("model", self.model.get()), ("custom_url", self.custom_url.get().strip()), ("write_editor", self.write_editor.get()), ("auto_run", self.auto_run.get()), ("auto_fix", self.auto_fix.get())):
            self.config.set(name, value)

    def _on_backend_event(self, name, event):
        if name in ("BackendRestart", "BackendTerminated", "ToplevelResponse"): self.refresh_hardware()

    def destroy(self):
        self.cancel_event.set(); self.adapter.close(); super().destroy()
