import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext, simpledialog, ttk

from thonny import get_runner, get_workbench
from thonny.plugins.ai_assistant.code_sanitizer import extract_code
from thonny.plugins.ai_assistant.config_manager import ConfigManager
from thonny.plugins.ai_assistant.device_setup import SetupState, choose_state, requests_esp32
from thonny.plugins.ai_assistant.hardware_context import detect_hardware
from thonny.plugins.ai_assistant.hil_agent import HilAgent, HilState
from thonny.plugins.ai_assistant.models import GenerationRequest
from thonny.plugins.ai_assistant.prompt_builder import build_messages, build_repair_messages
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
        self.device_status_text = tk.StringVar(value="Connect an ESP32 to begin")
        self.device_port = tk.StringVar()
        self.device_ports = {}
        self.pending_prompt = None
        self.hil = HilAgent(max_repairs=2)
        self.hil_status_text = tk.StringVar(value="HIL verification idle")
        self.current_requirement = ""
        self.generation_attempt = 0
        self._build_ui()
        self._provider_changed()
        self.refresh_hardware()
        self.after(40, self._drain_events)

    def _build_ui(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(3, weight=1)
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
        self.device_frame = ttk.LabelFrame(self, text="ESP32 setup", padding=5)
        self.device_frame.grid(row=1, column=0, sticky="ew", pady=(4, 2))
        self.device_frame.columnconfigure(0, weight=1)
        ttk.Label(self.device_frame, textvariable=self.device_status_text, wraplength=360).grid(
            row=0, column=0, columnspan=4, sticky="ew"
        )
        self.port_combo = ttk.Combobox(self.device_frame, textvariable=self.device_port, state="readonly")
        self.port_combo.grid(row=1, column=0, sticky="ew", pady=(4, 0))
        ttk.Button(self.device_frame, text="Scan", command=self.scan_esp32).grid(row=1, column=1, padx=(4, 0), pady=(4, 0))
        ttk.Button(self.device_frame, text="Configure", command=self.configure_esp32).grid(row=1, column=2, padx=(4, 0), pady=(4, 0))
        ttk.Button(self.device_frame, text="Install MicroPython…", command=self.install_micropython).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )
        ttk.Button(self.device_frame, text="Save as /main.py", command=self.save_main_to_device).grid(
            row=2, column=2, columnspan=2, sticky="e", pady=(4, 0)
        )
        self.device_frame.grid_remove()
        context = ttk.Frame(self)
        context.grid(row=2, column=0, sticky="ew", pady=(4, 2))
        ttk.Label(context, textvariable=self.hardware_text).pack(side="left", fill="x", expand=True)
        ttk.Button(context, text="↻", width=3, command=self.refresh_hardware).pack(side="right")
        ttk.Button(context, text="ESP32 setup", command=self.scan_esp32).pack(side="right", padx=(0, 4))
        self.chat = scrolledtext.ScrolledText(self, wrap="word", state="disabled", height=12)
        self.chat.grid(row=3, column=0, sticky="nsew")
        self.chat.tag_configure("user", foreground="#1769aa", spacing1=8)
        self.chat.tag_configure("assistant", foreground="#237a3b", spacing1=8)
        self.chat.tag_configure("error", foreground="#b3261e", spacing1=8)
        self.input = tk.Text(self, height=5, wrap="word", undo=True)
        self.input.grid(row=4, column=0, sticky="ew", pady=(5, 2))
        self.input.bind("<Control-Return>", self._send_event)
        self.input.bind("<Command-Return>", self._send_event)
        options = ttk.Frame(self)
        options.grid(row=5, column=0, sticky="ew")
        for label, var in (("Write to editor", self.write_editor), ("Auto-run", self.auto_run), ("Auto-fix", self.auto_fix)):
            ttk.Checkbutton(options, text=label, variable=var).pack(side="left")
        hil_frame = ttk.Frame(self)
        hil_frame.grid(row=6, column=0, sticky="ew", pady=(3, 0))
        ttk.Label(hil_frame, textvariable=self.hil_status_text).pack(
            side="left", fill="x", expand=True
        )
        self.hil_fail_button = ttk.Button(
            hil_frame,
            text="Result incorrect",
            command=self.reject_hardware_result,
            state="disabled",
        )
        self.hil_fail_button.pack(side="right")
        self.hil_pass_button = ttk.Button(
            hil_frame,
            text="Result correct",
            command=self.confirm_hardware_result,
            state="disabled",
        )
        self.hil_pass_button.pack(side="right", padx=4)
        ttk.Button(hil_frame, text="Run & verify", command=self.run_and_verify).pack(
            side="right"
        )
        buttons = ttk.Frame(self)
        buttons.grid(row=7, column=0, sticky="ew", pady=(3, 0))
        self.send_button = ttk.Button(buttons, text="Send", command=self.send)
        self.send_button.pack(side="right")
        self.cancel_button = ttk.Button(buttons, text="Cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right", padx=4)
        ttk.Button(buttons, text="Write code", command=self.write_last_code).pack(side="right")
        ttk.Button(buttons, text="Clear", command=self.clear).pack(side="left")
        ttk.Label(self, textvariable=self.status_text).grid(row=8, column=0, sticky="w", pady=(3, 0))

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
        if requests_esp32(prompt):
            hardware = self.refresh_hardware()
            if not (hardware.connected and hardware.platform == "ESP32"):
                self.pending_prompt = prompt
                self.device_frame.grid()
                self.history.append({"role": "user", "content": prompt})
                self._append_message("You", prompt, "user")
                self._append_message(
                    "Assistant",
                    "I’ll prepare the ESP32 first. Connect it with a data-capable USB cable; "
                    "I’ll select the interpreter and verify MicroPython before generating code.",
                    "assistant",
                )
                self.scan_esp32()
                return
        self._start_generation(prompt)

    def _start_generation(self, prompt, add_user=True):
        if add_user:
            self.history.append({"role": "user", "content": prompt})
            self._append_message("You", prompt, "user")
        self._append_message("Assistant", "", "assistant")
        self.current_requirement = prompt
        self.generation_attempt = 0
        self.last_assistant_text, self.cancel_event = "", threading.Event()
        request = GenerationRequest(self.model.get().strip(), build_messages(self.history, self.refresh_hardware()))
        self._save_preferences(); self._busy(True, "Generating…")
        self.worker = threading.Thread(target=self._generate_worker, args=(self._provider(), request, self.cancel_event), daemon=True)
        self.worker.start()

    def _start_repair(self, reason):
        run = self.hil.active
        if run is None:
            return
        self.hil.mark_repairing()
        self.generation_attempt = run.attempt + 1
        self._append_message("Assistant repair %d" % self.generation_attempt, "", "assistant")
        self.last_assistant_text, self.cancel_event = "", threading.Event()
        messages = build_repair_messages(
            run.requirement, run.code, run.output, reason, self.refresh_hardware()
        )
        request = GenerationRequest(self.model.get().strip(), messages)
        self._busy(True, "Repairing from target evidence…")
        self.worker = threading.Thread(
            target=self._generate_worker,
            args=(self._provider(), request, self.cancel_event),
            daemon=True,
        )
        self.worker.start()

    def scan_esp32(self):
        self.device_frame.grid()
        try:
            choices = self.adapter.list_esp32_ports()
            self.device_ports = {choice.label: choice for choice in choices}
            labels = [choice.label for choice in choices]
            self.port_combo["values"] = labels
            if not labels:
                self.device_port.set("")
                self.device_status_text.set("1/4 Connect the ESP32 with a data-capable USB cable, then click Scan.")
                return
            likely = [choice for choice in choices if choice.likely_esp32]
            selected = likely[0] if len(likely) == 1 else choices[0]
            self.device_port.set(selected.label)
            if len(choices) == 1 or len(likely) == 1:
                self.configure_esp32()
            else:
                self.device_status_text.set("1/4 Select the ESP32 serial port, then click Configure.")
        except Exception as exc:
            self.device_status_text.set("Could not scan serial ports: %s" % exc)

    def configure_esp32(self):
        choice = self.device_ports.get(self.device_port.get())
        if choice is None:
            messagebox.showinfo("ESP32 setup", "Connect the board and select its serial port first.", parent=self)
            return
        try:
            self.device_status_text.set("2/4 Selecting the ESP32 interpreter and checking MicroPython…")
            self.adapter.configure_esp32(choice.device)
        except Exception as exc:
            self.device_status_text.set("Could not configure ESP32: %s" % exc)

    def install_micropython(self):
        try:
            self.device_status_text.set("Use Thonny’s installer to erase and install MicroPython firmware.")
            new_port = self.adapter.open_esp32_firmware_installer()
            self.scan_esp32()
            if new_port:
                for label, choice in self.device_ports.items():
                    if choice.device == new_port:
                        self.device_port.set(label)
                        self.configure_esp32()
                        break
        except Exception as exc:
            messagebox.showerror("ESP32 setup", str(exc), parent=self)

    def save_main_to_device(self):
        try:
            cleaned = extract_code(self.last_assistant_text)
            if not cleaned.code.strip():
                raise RuntimeError("Generate MicroPython code first")
            if not messagebox.askyesno(
                "Save to ESP32",
                "Save the generated code as /main.py? This replaces the existing /main.py and runs after reset.",
                parent=self,
            ):
                return False
            self.adapter.write_main_to_device(cleaned.code)
            self.device_status_text.set("4/4 Saved /main.py. Press Run in Thonny or reset the ESP32.")
            return True
        except Exception as exc:
            messagebox.showerror("ESP32 setup", str(exc), parent=self)
            return False

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

    def write_last_code(self, silent=False, force_run=False):
        try:
            cleaned = extract_code(self.last_assistant_text)
            if cleaned.warnings:
                if silent: self.status_text.set("Code has warnings; review before writing"); return False
                if not messagebox.askyesno("AI Assistant", "\n".join(cleaned.warnings) + "\n\nWrite anyway?", parent=self): return False
            self.adapter.write_editor(cleaned.code)
            if self.auto_run.get() or force_run:
                decision = self.hil.start(
                    self.current_requirement, cleaned.code, attempt=self.generation_attempt
                )
                self._handle_hil_decision(decision)
                if decision.state == HilState.ARMED:
                    try:
                        self.adapter.execute_current()
                    except Exception as exc:
                        self._handle_hil_decision(self.hil.execution_rejected(str(exc)))
                        raise
            self.status_text.set("Code written to editor")
            return True
        except Exception as exc:
            if silent: self.status_text.set(str(exc))
            else: messagebox.showerror("AI Assistant", str(exc), parent=self)
            return False

    def run_and_verify(self):
        return self.write_last_code(force_run=True)

    def cancel(self): self.cancel_event.set(); self.status_text.set("Cancelling…")

    def clear(self):
        self.history.clear(); self.last_assistant_text = ""
        self.hil = HilAgent(max_repairs=2)
        self._set_observation_buttons(False)
        self.hil_status_text.set("HIL verification idle")
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
        if name == "ProgramOutput":
            self._handle_hil_decision(self.hil.feed_output(getattr(event, "data", "")))
            return
        if name == "CommandAccepted":
            command = getattr(event, "command", None)
            decision = self.hil.command_accepted(getattr(command, "name", ""))
            self._handle_hil_decision(decision)
            if decision and decision.state == HilState.RUNNING:
                run_id = self.hil.active.run_id
                self.after(
                    5000,
                    lambda: self._handle_hil_decision(
                        self.hil.observation_timeout(run_id)
                    ),
                )
            return
        if name == "InputRequest":
            self._handle_hil_decision(self.hil.input_requested())
            return
        if name not in ("BackendRestart", "BackendTerminated", "ToplevelResponse"):
            return
        hardware = self.refresh_hardware()
        state = choose_state([], hardware.board, hardware.connected)
        if name == "BackendRestart":
            self.device_status_text.set("2/4 Checking the ESP32 and MicroPython firmware…")
        elif name == "BackendTerminated" and self.pending_prompt:
            self.device_frame.grid()
            self.device_status_text.set(
                "MicroPython did not start. Check the USB connection; if the board is blank or uses other firmware, click Install MicroPython."
            )
        elif name == "BackendTerminated":
            self._handle_hil_decision(self.hil.disconnected())
        elif name == "ToplevelResponse" and state == SetupState.READY:
            self.device_frame.grid()
            self.device_status_text.set("3/4 ESP32 is connected and MicroPython is ready. Generating your program…")
            if self.pending_prompt:
                prompt, self.pending_prompt = self.pending_prompt, None
                self.after_idle(lambda: self._start_generation(prompt, add_user=False))
            else:
                self._handle_hil_decision(self.hil.toplevel_finished())

    def _handle_hil_decision(self, decision):
        if decision is None:
            return
        self.hil_status_text.set("HIL: " + decision.reason)
        awaiting = decision.state == HilState.AWAITING_OBSERVATION
        self._set_observation_buttons(awaiting)
        if decision.state == HilState.PASSED:
            self._append_message("Verification", "Passed: " + decision.reason, "assistant")
        elif decision.state == HilState.FAILED:
            self._append_message("Verification", "Failed: " + decision.reason, "error")
            if decision.request_repair and self.auto_fix.get():
                self.after_idle(lambda reason=decision.reason: self._start_repair(reason))
        elif decision.state in (HilState.DISCONNECTED, HilState.WAITING_INPUT):
            self._append_message("Verification", decision.reason, "error")

    def _set_observation_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        self.hil_pass_button.configure(state=state)
        self.hil_fail_button.configure(state=state)

    def confirm_hardware_result(self):
        self._handle_hil_decision(self.hil.observe(True, "User confirmed the hardware behavior"))

    def reject_hardware_result(self):
        feedback = simpledialog.askstring(
            "Hardware observation",
            "What did the hardware do instead? This evidence will be sent for repair.",
            parent=self,
        )
        if feedback is not None:
            self._handle_hil_decision(self.hil.observe(False, feedback.strip()))

    def destroy(self):
        self.cancel_event.set(); self.adapter.close(); super().destroy()
