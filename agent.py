"""
Autonomous Computer Control Agent Harness (AIM-VR 3.0).

Dynamic, tool-discovering agent runner for Windows desktop automation.
Translates user instructions into structured action sequences using local or remote LLMs,
dispatches execution via the native AIM-VR engine, and reports captured results.
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

# Ensure project root is available for imports
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from control.clipboard import default_clipboard
from control.safety import default_governor
from server import MCPServer


class ToolRegistry:
    """Discovers available tools and action schemas dynamically from repository metadata."""

    def __init__(self, schemas_dir: Optional[str] = None):
        self.schemas_dir = schemas_dir or os.path.join(PROJECT_ROOT, "mcp_schemas")
        self.task_schema = self._load_schema("execute_autonomous_task.json")
        self.dag_schema = self._load_schema("execute_action_dag.json")

    def _load_schema(self, filename: str) -> Dict[str, Any]:
        path = os.path.join(self.schemas_dir, filename)
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                sys.stderr.write(f"[ToolRegistry] Warning: could not load {filename}: {e}\n")
        return {}

    def get_supported_actions(self) -> List[str]:
        """Returns the list of supported action types from the schema."""
        try:
            properties = self.task_schema["parameters"]["properties"]["steps"]["items"]["properties"]
            return properties.get("action", {}).get("enum", [])
        except (KeyError, TypeError):
            return [
                "click", "double_click", "right_click", "triple_click", "hover", "move",
                "type_text", "paste_text", "press_key", "hotkey", "wait", "focus_window",
                "close_window", "launch_app", "manage_window", "control_media", "invoke_element", "set_value"
            ]

    def get_capabilities_summary(self) -> str:
        """Builds a formatted reference of available actions and their parameters."""
        actions = self.get_supported_actions()
        lines = [
            f"Available Actions ({len(actions)} total):",
            "- launch_app: Launch executable or app alias. Parameters: name (str, e.g. 'calc.exe', 'notepad', 'chrome', 'explorer'), args (str, optional).",
            "- wait: Pause execution for window rendering or process settlement. Parameters: seconds (float, e.g. 1.0, 1.5).",
            "- click / double_click / right_click: Click UI elements. Parameters: target (str, window title substring), query (str, visible label/text e.g. 'File', '7', 'Multiply', 'Save').",
            "- type_text: Simulate typing Unicode text. Parameters: text (str), target (str, optional), interval (float, optional).",
            "- paste_text: Instant atomic clipboard paste. Best for long strings or code. Parameters: text (str), target (str, optional).",
            "- hotkey: Trigger keyboard combinations. Parameters: keys (list of str, e.g. ['ctrl', 'c'], ['ctrl', 's'], ['win', 'r'], ['alt', 'tab']), target (str, optional).",
            "- press_key: Press single key. Parameters: key (str, e.g. 'enter', 'tab', 'esc', 'backspace'), target (str, optional).",
            "- manage_window: Adjust window layout. Parameters: target (str, window title), sub_action ('snap' | 'state'), position ('left' | 'right' | 'top' | 'bottom' | 'center'), state ('maximize' | 'minimize' | 'restore').",
            "- focus_window: Bring window to foreground. Parameters: target (str, window title substring).",
            "- close_window: Safely dispatch WM_CLOSE to window. Parameters: target (str, window title substring), force (bool, optional).",
            "- control_media: Adjust audio or media playback. Parameters: sub_action ('volume_up' | 'volume_down' | 'toggle_mute' | 'play_pause'), steps (int, optional).",
        ]
        return "\n".join(lines)


class PromptBuilder:
    """Builds model-agnostic system prompts dynamically using the tool registry."""

    def __init__(self, registry: ToolRegistry, sandbox: bool = False):
        self.registry = registry
        self.sandbox = sandbox

    def build_system_prompt(self) -> str:
        capabilities = self.registry.get_capabilities_summary()
        sandbox_section = ""
        if self.sandbox:
            sandbox_section = """
### Desktop Mode: ISOLATED VIRTUAL DESKTOP SANDBOX (WinSta0\\AIMVR_Sandbox):
- You are executing inside an isolated background desktop sandbox.
- Your actions run in the background without moving the user's physical mouse cursor or stealing keyboard focus.
- For all window-specific steps (click, type_text, paste_text, press_key, hotkey, close_window), ALWAYS set 'target' to the application window title substring (e.g. target='Notepad', target='Calculator').
- Use 'launch_app' to spawn target applications into the sandbox.
"""
        return f"""You are an autonomous computer control agent for Windows 10/11 powered by AIM-VR 3.0.
Your objective is to translate user natural language requests into a sequence of concrete desktop actions.
{sandbox_section}
### Discovered Capabilities & Tools:
{capabilities}

### Operational Rules:
1. Application Lifecycle: Always insert a wait step (seconds=1.0 to 1.5) immediately after launch_app so the GUI window has time to spawn and paint.
2. Element Targeting: When interacting with an application, set target to the application's window title substring (e.g. 'Calculator', 'Notepad', 'Chrome') and query to the exact button label or text (e.g. query='7', query='File', query='Save').
3. Extracting Results: If the user instruction requires reading a calculation, status, or text from an application, send hotkey keys=['ctrl', 'c'] while the application is focused to copy the result to the Windows clipboard before closing the window.
4. Window Cleanup: If the user task specifies closing the application after completing the action, include close_window at the end. Otherwise leave it open.
5. Strict JSON Output: Output ONLY a valid JSON object matching this schema without markdown code blocks or conversational commentary:
{{
  "thought": "Brief technical description of plan and target window interactions",
  "steps": [
    {{"action": "launch_app", "name": "...", "description": "..."}},
    {{"action": "wait", "seconds": 1.0, "description": "..."}}
  ]
}}
"""


class OllamaPlanner:
    """Handles communication with the local Ollama LLM endpoint."""

    def __init__(self, model: str = "gemma4:e4b", url: str = "http://127.0.0.1:11434/api/generate"):
        self.model = model
        self.url = url

    def plan(self, system_prompt: str, user_task: str, timeout: int = 120) -> Dict[str, Any]:
        full_prompt = f"{system_prompt}\nUser Request: {user_task}\nJSON Plan:"
        payload = {
            "model": self.model,
            "prompt": full_prompt,
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1
            }
        }

        req = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )

        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise RuntimeError(f"Failed to query Ollama at {self.url}: {e}")

        raw_text = data.get("response", "").strip()
        cleaned_json = self._clean_json(raw_text)

        try:
            parsed = json.loads(cleaned_json)
        except Exception as e:
            raise ValueError(f"Model generated invalid JSON ({e}). Raw response:\n{raw_text}")

        eval_count = data.get("eval_count", 0)
        eval_duration_ns = data.get("eval_duration", 1)
        tokens_per_sec = (eval_count / (eval_duration_ns / 1e9)) if eval_duration_ns else 0
        parsed["_meta"] = {
            "tokens_per_sec": round(tokens_per_sec, 1),
            "eval_count": eval_count,
        }
        return parsed

    @staticmethod
    def _clean_json(text: str) -> str:
        s = text.strip()
        if s.startswith("```"):
            lines = s.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            s = "\n".join(lines).strip()
        return s


class ExecutionHarness:
    """Executes validated multi-step plans via MCPServer and captures results."""

    def __init__(self, verify: bool = True, sandbox: bool = False):
        self.verify = verify
        self.sandbox = sandbox
        desktop_mode = "isolated_pip" if sandbox else "interactive"
        default_governor.configure(failsafe=False, desktop_mode=desktop_mode)
        self.server = MCPServer()

    def execute(self, plan: Dict[str, Any], save_path: Optional[str] = "plan_latest.json") -> Tuple[Dict[str, Any], Optional[str]]:
        steps = plan.get("steps", [])
        if not steps:
            raise ValueError("Plan contains no action steps.")

        if save_path:
            with open(save_path, "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2)

        # Clear clipboard prior to run so newly copied values are cleanly detected
        default_clipboard.set_text("")

        content, is_error = self.server.execute_tool("execute_autonomous_task", {
            "steps": steps,
            "verify": self.verify
        })

        summary = {}
        if content and len(content) > 0:
            try:
                summary = json.loads(content[0].get("text", "{}"))
            except Exception:
                summary = {"raw": content[0].get("text", "")}

        captured_clipboard = default_clipboard.get_text().strip()
        result_text = captured_clipboard if captured_clipboard else None

        return summary, result_text


class AgentHarness:
    """Main coordinator uniting discovery, planning, and execution."""

    def __init__(
        self,
        model: str = "gemma4:e4b",
        ollama_url: str = "http://127.0.0.1:11434/api/generate",
        verify: bool = True,
        sandbox: bool = False,
    ):
        self.sandbox = sandbox
        self.registry = ToolRegistry()
        self.prompt_builder = PromptBuilder(self.registry, sandbox=sandbox)
        self.planner = OllamaPlanner(model=model, url=ollama_url)
        self.harness = ExecutionHarness(verify=verify, sandbox=sandbox)

    def run_task(self, task: str, plan_only: bool = False, verbose: bool = False) -> bool:
        mode_label = "Isolated PiP Sandbox (WinSta0\\AIMVR_Sandbox)" if self.sandbox else "Interactive Desktop"
        print(f"\n[Task]: {task}")
        print(f"[Execution Mode]: {mode_label}")
        system_prompt = self.prompt_builder.build_system_prompt()

        if verbose:
            print("[System Prompt]:\n", system_prompt)

        print(f"[Planning]: Querying model '{self.planner.model}'...")
        start_t = time.perf_counter()
        try:
            plan = self.planner.plan(system_prompt, task)
        except Exception as e:
            print(f"[Error]: {e}", file=sys.stderr)
            return False

        gen_elapsed = time.perf_counter() - start_t
        meta = plan.get("_meta", {})
        steps = plan.get("steps", [])
        thought = plan.get("thought", "None provided")

        print(f"[Plan Generated]: {len(steps)} steps in {gen_elapsed:.2f}s ({meta.get('tokens_per_sec', 0)} tok/s)")
        print(f"[Thought]: {thought}")

        for idx, s in enumerate(steps, 1):
            desc = s.get("description") or s.get("query") or s.get("name") or s.get("action")
            print(f"  Step {idx}: {s.get('action')} -> {desc}")

        if plan_only:
            with open("plan_latest.json", "w", encoding="utf-8") as f:
                json.dump(plan, f, indent=2)
            print("[Plan saved to plan_latest.json (plan-only mode)]")
            return True

        print("\n[Executing]: Running steps via AIM-VR engine...")
        exec_start = time.perf_counter()
        try:
            summary, captured_result = self.harness.execute(plan)
        except Exception as e:
            print(f"[Execution Error]: {e}", file=sys.stderr)
            return False

        exec_elapsed = time.perf_counter() - exec_start
        status = summary.get("status", "unknown")
        completed = summary.get("completed_steps", 0)

        print(f"[Completed]: Status={status} | Completed {completed}/{len(steps)} steps in {exec_elapsed:.2f}s")

        if captured_result:
            print(f"\n==========================================")
            print(f"Captured Result: {captured_result}")
            print(f"==========================================\n")

        return status == "success"

    def interactive_loop(self):
        print("AIM-VR Agent Interactive Harness")
        print("Type your desktop command (or 'exit' / 'quit' to finish).\n")
        while True:
            try:
                task_input = input("Agent> ").strip()
                if not task_input:
                    continue
                if task_input.lower() in ["exit", "quit", "q"]:
                    print("Exiting harness.")
                    break
                self.run_task(task_input)
            except (KeyboardInterrupt, EOFError):
                print("\nSession interrupted.")
                break


def parse_cli_args():
    parser = argparse.ArgumentParser(description="AIM-VR Autonomous Computer Control Harness")
    parser.add_argument(
        "command",
        nargs="?",
        default=None,
        help="Natural language instruction for the desktop automation task."
    )
    parser.add_argument(
        "--interactive", "-i",
        action="store_true",
        help="Start interactive conversational prompt loop."
    )
    parser.add_argument(
        "--model", "-m",
        default="gemma4:e4b",
        help="Ollama model identifier (default: gemma4:e4b)."
    )
    parser.add_argument(
        "--ollama-url",
        default="http://127.0.0.1:11434/api/generate",
        help="Ollama generation endpoint."
    )
    parser.add_argument(
        "--plan-only",
        action="store_true",
        help="Synthesize and inspect plan without executing."
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Disable visual servoing reaction verification."
    )
    parser.add_argument(
        "--sandbox", "-s",
        action="store_true",
        help="Run automation in isolated background virtual desktop (AIMVR_Sandbox) without moving mouse cursor or taking window focus."
    )
    parser.add_argument(
        "--pip-window", "-w",
        action="store_true",
        help="Launch an Always-On-Top floating Picture-in-Picture window previewing sandbox desktop activity."
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Display verbose prompts and metadata."
    )
    return parser.parse_args()


def main():
    args = parse_cli_args()
    pip_proc = None
    if args.pip_window:
        import subprocess
        viewer_script = os.path.join(PROJECT_ROOT, "pip_viewer.py")
        pip_proc = subprocess.Popen([sys.executable, viewer_script])

    agent = AgentHarness(
        model=args.model,
        ollama_url=args.ollama_url,
        verify=not args.no_verify,
        sandbox=args.sandbox or args.pip_window,
    )

    try:
        if args.interactive or args.command is None:
            agent.interactive_loop()
        else:
            success = agent.run_task(args.command, plan_only=args.plan_only, verbose=args.verbose)
            if not success:
                sys.exit(1)
    finally:
        # Keep viewer open or allow user to inspect until closed
        pass


if __name__ == "__main__":
    main()
