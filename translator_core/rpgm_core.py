from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TextIO

from .models import JobResult
from .utils import create_backup_snapshot, ensure_directory

IGNORAR_ARQUIVOS = ["System.json", "Tilesets.json", "Animations.json"]

TRANSLATIONS_FILENAME = "rpgm_translations.txt"
PLACEHOLDERS_FILENAME = "rpgm_placeholders.txt"
MAP_FILENAME = "rpgm_mapa_arquivos.json"
IMPORT_LOG_FILENAME = "rpgm_import_log.txt"
RPGM_DIALOGUE_WRAP_LIMIT = 78

OVERLAY_PLUGIN_NAME = "InterfaceTradutoresOverlay"
OVERLAY_PLUGIN_FILENAME = f"{OVERLAY_PLUGIN_NAME}.js"

_SCRIPT_PHRASE_RE = re.compile(r'"([^"]{3,})"')
_TECHNICAL_FILE_EXT_RE = re.compile(
    r"\.(png|jpe?g|gif|webp|svg|bmp|ico|mp3|ogg|wav|m4a|webm|mp4|avi|mov|"
    r"json|js|css|ttf|otf|woff2?|rpgmvp|rpgmvm|rpgmvo|rpgmvv|exe|dll)(?:$|\?)",
    flags=re.IGNORECASE,
)
_URL_RE = re.compile(r"^(https?://|www\.)", flags=re.IGNORECASE)
_HEX_COLOR_RE = re.compile(r"^#?[0-9a-f]{6}(?:[0-9a-f]{2})?$", flags=re.IGNORECASE)
_HAS_LETTER_RE = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
_PLUGIN_ASSIGN_RE = re.compile(r"\$plugins\s*=\s*(\[[\s\S]*\])\s*;?", flags=re.MULTILINE)

_GENERIC_TECHNICAL_KEYS = {
    "path",
    "filepath",
    "filename",
    "folder",
    "directory",
    "dir",
    "src",
    "url",
    "class",
    "type",
    "plugin",
    "pluginname",
    "script",
    "command",
    "eventid",
    "switchid",
    "variableid",
    "actorid",
    "enemyid",
    "id",
    "code",
    "hash",
    "uuid",
}

_ASSET_KEY_TOKENS = {
    "img",
    "image",
    "picture",
    "sprite",
    "icon",
    "face",
    "character",
    "battler",
    "tileset",
    "parallax",
    "background",
    "bg",
    "bgm",
    "bgs",
    "se",
    "me",
    "voice",
    "audio",
    "sound",
    "video",
    "movie",
    "windowskin",
    "filename",
    "filepath",
}

_GENERIC_ALLOWED_KEY_TOKENS = {
    "text",
    "title",
    "subtitle",
    "label",
    "caption",
    "message",
    "content",
    "description",
    "desc",
    "hint",
    "help",
    "prompt",
    "question",
    "answer",
    "option",
    "choice",
    "header",
    "body",
    "name",
    "display",
    "displayname",
    "displaytext",
    "appname",
    "username",
    "notification",
}

_GENERIC_BLOCKED_KEY_TOKENS = {
    "debug",
    "preset",
    "command",
    "condition",
    "event",
    "switch",
    "variable",
    "map",
    "scene",
    "container",
    "layout",
    "style",
    "animation",
    "duration",
    "opacity",
    "rotation",
    "margins",
    "corner",
    "fill",
    "stroke",
    "outline",
    "font",
    "weight",
    "size",
    "width",
    "height",
    "tint",
    "color",
    "alpha",
    "x",
    "y",
    "z",
    "root",
    "center",
    "left",
    "right",
    "top",
    "bottom",
    "shadow",
    "field",
    "keyframe",
    "script",
    "code",
}

_TECHNICAL_TEXT_RE = re.compile(
    r"("
    r"@pkd_|"
    r"galv\.|"
    r"foldername:|"
    r"imagename:|"
    r"fillcolor:|"
    r"strokewidth:|"
    r"strokecolor:|"
    r"strokealpha:|"
    r"keyframes:|"
    r"duration:|"
    r"field:|"
    r"clickse:|"
    r"keyboardkey:|"
    r"tint:|"
    r"overtint:|"
    r"activetint:|"
    r"margins:|"
    r"keepaspect|"
    r"\b\d+\s*(hdp|dp)\b|"
    r"^\s*\|\|\s*$|"
    r"^\s*>\s+|"
    r"^\s*=+|"
    r"^\s*(center|shadow|left|right|top|bottom|root)\s*$"
    r")",
    flags=re.IGNORECASE,
)


@dataclass
class _TextTarget:
    protected_text: str
    placeholders: list[str]
    apply: Callable[[str], None]


def expected_workspace_files() -> list[str]:
    return [TRANSLATIONS_FILENAME, PLACEHOLDERS_FILENAME, MAP_FILENAME]


def _iter_rpgm_json_files(data_dir: Path) -> list[Path]:
    return sorted(
        [
            path
            for path in data_dir.rglob("*.json")
            if path.is_file() and path.name not in IGNORAR_ARQUIVOS
        ],
        key=lambda path: path.relative_to(data_dir).as_posix().lower(),
    )


def resolve_rpgm_data_dir(project_dir: str | Path) -> Path | None:
    project = Path(project_dir)
    if not project.exists() or not project.is_dir():
        return None

    for candidate in [project / "www" / "data", project / "data", project]:
        if candidate.exists() and candidate.is_dir() and _iter_rpgm_json_files(candidate):
            return candidate

    return None


def describe_rpgm_data_dir(project_dir: str | Path, data_dir: str | Path) -> str:
    project = Path(project_dir).resolve()
    data = Path(data_dir).resolve()

    try:
        relative = data.relative_to(project)
    except ValueError:
        return str(data)

    text = relative.as_posix()
    return text if text != "." else "(pasta selecionada)"


def resolve_rpgm_runtime_root(project_dir: str | Path) -> Path | None:
    project = Path(project_dir)
    data_dir = resolve_rpgm_data_dir(project)

    candidates: list[Path] = [project, project / "www"]
    if data_dir is not None:
        candidates.append(data_dir.parent)
        if data_dir.parent.name.lower() == "www":
            candidates.append(data_dir.parent.parent)
    if project.name.lower() == "data":
        candidates.append(project.parent)

    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)

    for candidate in unique:
        js_dir = candidate / "js"
        plugins_js = js_dir / "plugins.js"
        if js_dir.exists() and js_dir.is_dir() and plugins_js.exists() and plugins_js.is_file():
            return candidate

    return None


def detectar_runtime_rpgm(project_dir: str | Path) -> str | None:
    runtime_root = resolve_rpgm_runtime_root(project_dir)
    if runtime_root is None:
        return None

    js_dir = runtime_root / "js"
    if (js_dir / "rmmz_core.js").exists():
        return "mz"
    if (js_dir / "rpg_core.js").exists():
        return "mv"
    return None


def _overlay_plugin_source() -> str:
    return r"""/*:
 * @target MV MZ
 * @plugindesc Interface Tradutores - Overlay de texto para diálogo (MV/MZ)
 * @author Interface Tradutores
 */
(() => {
  "use strict";

  const STORAGE_KEY = "InterfaceTradutoresOverlay:v1";
  const DEFAULTS = {
    fontSize: 28,
    lineHeight: 36,
    wrapLimit: 78,
    visibleRows: 4,
    panelOpen: false
  };

  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const rtrim = (value) => String(value).replace(/\s+$/, "");
  const ltrim = (value) => String(value).replace(/^\s+/, "");

  const protectTokens = (text) => {
    const tokens = [];
    const safe = String(text).replace(
      /\\[A-Za-z_]+(?:\[[^\]]+\])?|\\[\\><\^._\|!\$\{\}\[\]]|<[^>]+>/g,
      (m) => {
        const idx = tokens.push(m) - 1;
        return `__ITPH_${idx}__`;
      }
    );
    return { safe, tokens };
  };

  const restoreTokens = (text, tokens) => {
    let result = String(text);
    tokens.forEach((token, idx) => {
      result = result.split(`__ITPH_${idx}__`).join(token);
    });
    return result;
  };

  const wrapTextByLimit = (text, limit) => {
    const numeric = Number(limit) || 0;
    if (!text || numeric <= 0) return text;

    const rows = String(text).split("\n");
    const wrapped = rows.map((row) => {
      if (row.length <= numeric) return row;

      const protectedRow = protectTokens(row);
      const parts = protectedRow.safe.split(/(\s+)/);
      const lines = [];
      let current = "";

      for (const part of parts) {
        if (!part) continue;
        const candidate = current ? current + part : part;
        if (current && !/^\s+$/.test(part) && candidate.length > numeric) {
          lines.push(rtrim(current));
          current = ltrim(part);
        } else {
          current = candidate;
        }
      }

      if (current.trim()) {
        lines.push(rtrim(current));
      }

      return restoreTokens(lines.join("\n"), protectedRow.tokens);
    });

    return wrapped.join("\n");
  };

  const loadSettings = () => {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      if (!raw) return { ...DEFAULTS };
      const parsed = JSON.parse(raw);
      return {
        fontSize: clamp(Number(parsed.fontSize) || DEFAULTS.fontSize, 16, 64),
        lineHeight: clamp(Number(parsed.lineHeight) || DEFAULTS.lineHeight, 24, 96),
        wrapLimit: clamp(Number(parsed.wrapLimit) || DEFAULTS.wrapLimit, 28, 140),
        visibleRows: clamp(Number(parsed.visibleRows) || DEFAULTS.visibleRows, 2, 8),
        panelOpen: Boolean(parsed.panelOpen)
      };
    } catch (_err) {
      return { ...DEFAULTS };
    }
  };

  const saveSettings = (settings) => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    } catch (_err) {
      // sem bloqueio
    }
  };

  const state = {
    settings: loadSettings(),
    uiCreated: false,
    pendingWindowRefresh: false
  };

  const messageWindow = () => {
    const scene = SceneManager._scene;
    if (!scene || !scene._messageWindow) return null;
    return scene._messageWindow;
  };

  const isMessageActive = () => {
    const win = messageWindow();
    if (!win) return false;
    if (win._textState && typeof win._textState.index === "number") return true;
    if (typeof $gameMessage !== "undefined" && $gameMessage && typeof $gameMessage.isBusy === "function") {
      try {
        if ($gameMessage.isBusy()) return true;
      } catch (_err) {
        // compatibilidade
      }
    }
    return false;
  };

  const refreshMessageWindow = () => {
    const win = messageWindow();
    if (!win) return false;
    if (isMessageActive()) {
      state.pendingWindowRefresh = true;
      return false;
    }
    state.pendingWindowRefresh = false;
    // Refresh seguro: evita recriar/reiniciar a mensagem atual, o que pode
    // apagar o texto em alguns runtimes (MV/MZ antigos/modificados).
    if (typeof win.resetFontSettings === "function") {
      try {
        win.resetFontSettings();
      } catch (_err) {
        // Mantém compatibilidade.
      }
    }
    if (typeof win.updatePlacement === "function") {
      win.updatePlacement();
    }
    // Em alguns runtimes, limpar e redesenhar durante mensagem ativa apaga o texto.
    // Por segurança, as mudanças ficam garantidas para o próximo diálogo.
    return true;
  };

  const applyChange = (key, value) => {
    state.settings[key] = value;
    saveSettings(state.settings);
    refreshMessageWindow();
  };

  const bindOverlayInputGuards = (element) => {
    if (!element) return;
    const events = [
      "mousedown",
      "mouseup",
      "click",
      "dblclick",
      "pointerdown",
      "pointerup",
      "touchstart",
      "touchend",
      "touchmove",
      "wheel",
      "contextmenu"
    ];
    events.forEach((eventName) => {
      element.addEventListener(eventName, (event) => {
        event.stopPropagation();
        if (typeof event.stopImmediatePropagation === "function") {
          event.stopImmediatePropagation();
        }
      });
    });
  };

  const createSliderRow = (panel, label, key, min, max, step) => {
    const row = document.createElement("div");
    row.style.marginBottom = "8px";

    const title = document.createElement("div");
    title.style.font = "12px sans-serif";
    title.style.marginBottom = "2px";
    title.textContent = `${label}: ${state.settings[key]}`;

    const slider = document.createElement("input");
    slider.type = "range";
    slider.min = String(min);
    slider.max = String(max);
    slider.step = String(step);
    slider.value = String(state.settings[key]);
    slider.style.width = "170px";
    slider.addEventListener("input", () => {
      const numericValue = Number(slider.value);
      title.textContent = `${label}: ${numericValue}`;
      applyChange(key, numericValue);
    });

    row.appendChild(title);
    row.appendChild(slider);
    panel.appendChild(row);
  };

  const ensureUi = () => {
    if (state.uiCreated) return;
    state.uiCreated = true;

    const button = document.createElement("button");
    button.id = "it-overlay-toggle";
    button.type = "button";
    button.style.position = "fixed";
    button.style.width = "18px";
    button.style.height = "18px";
    button.style.padding = "0";
    button.style.border = "1px solid rgba(255,255,255,0.75)";
    button.style.borderRadius = "999px";
    button.style.background = "rgba(15,15,20,0.55)";
    button.style.cursor = "pointer";
    button.style.zIndex = "2147483647";
    button.style.display = "none";
    button.title = "Ajuste de texto";

    const panel = document.createElement("div");
    panel.id = "it-overlay-panel";
    panel.style.position = "fixed";
    panel.style.width = "190px";
    panel.style.padding = "8px 10px";
    panel.style.borderRadius = "8px";
    panel.style.background = "rgba(16,18,24,0.92)";
    panel.style.border = "1px solid rgba(255,255,255,0.18)";
    panel.style.color = "#f3f6ff";
    panel.style.zIndex = "2147483647";
    panel.style.display = state.settings.panelOpen ? "block" : "none";
    panel.style.userSelect = "none";

    createSliderRow(panel, "Fonte", "fontSize", 16, 64, 1);
    createSliderRow(panel, "Altura linha", "lineHeight", 24, 96, 1);
    createSliderRow(panel, "Quebra (wrap)", "wrapLimit", 28, 140, 1);
    createSliderRow(panel, "Linhas visíveis", "visibleRows", 2, 8, 1);

    button.addEventListener("click", () => {
      state.settings.panelOpen = !state.settings.panelOpen;
      saveSettings(state.settings);
      panel.style.display = state.settings.panelOpen ? "block" : "none";
    });

    bindOverlayInputGuards(button);
    bindOverlayInputGuards(panel);

    document.body.appendChild(button);
    document.body.appendChild(panel);
  };

  const positionUi = () => {
    ensureUi();
    if (state.pendingWindowRefresh && !isMessageActive()) {
      refreshMessageWindow();
    }
    const button = document.getElementById("it-overlay-toggle");
    const panel = document.getElementById("it-overlay-panel");
    const win = messageWindow();

    if (!button || !panel || !win || !win.visible || win.openness <= 0) {
      if (button) button.style.display = "none";
      if (panel && state.settings.panelOpen) panel.style.display = "none";
      return;
    }

    const canvas = Graphics._canvas || document.querySelector("canvas");
    const rect = canvas
      ? canvas.getBoundingClientRect()
      : { left: 0, top: 0, width: Graphics.boxWidth, height: Graphics.boxHeight };
    const scaleX = Graphics.boxWidth > 0 ? rect.width / Graphics.boxWidth : 1;
    const scaleY = Graphics.boxHeight > 0 ? rect.height / Graphics.boxHeight : 1;

    const bx = rect.left + (win.x + win.width - 20) * scaleX;
    const by = rect.top + (win.y + win.height - 20) * scaleY;

    button.style.left = `${Math.round(bx)}px`;
    button.style.top = `${Math.round(by)}px`;
    button.style.display = "block";

    const panelWidth = panel.offsetWidth || 190;
    const panelHeight = panel.offsetHeight || 200;
    const px = clamp(
      Math.round(bx - panelWidth + 18),
      Math.round(rect.left + 6),
      Math.round(rect.left + rect.width - panelWidth - 6)
    );
    const py = clamp(
      Math.round(by - panelHeight - 6),
      Math.round(rect.top + 6),
      Math.round(rect.top + rect.height - panelHeight - 6)
    );

    panel.style.left = `${px}px`;
    panel.style.top = `${py}px`;
    panel.style.display = state.settings.panelOpen ? "block" : "none";
  };

  const _Window_Message_standardFontSize = Window_Message.prototype.standardFontSize;
  Window_Message.prototype.standardFontSize = function() {
    return clamp(Number(state.settings.fontSize) || _Window_Message_standardFontSize.call(this), 16, 64);
  };

  const _Window_Message_lineHeight = Window_Message.prototype.lineHeight;
  Window_Message.prototype.lineHeight = function() {
    return clamp(Number(state.settings.lineHeight) || _Window_Message_lineHeight.call(this), 24, 96);
  };

  const _Window_Message_numVisibleRows = Window_Message.prototype.numVisibleRows;
  Window_Message.prototype.numVisibleRows = function() {
    return clamp(Number(state.settings.visibleRows) || _Window_Message_numVisibleRows.call(this), 2, 8);
  };

  const _Window_Message_startMessage = Window_Message.prototype.startMessage;
  Window_Message.prototype.startMessage = function() {
    _Window_Message_startMessage.call(this);
    if (this._textState && typeof this._textState.text === "string") {
      this._textState.text = wrapTextByLimit(this._textState.text, state.settings.wrapLimit);
    }
  };

  const hookSceneUpdate = (sceneClass) => {
    if (!sceneClass || !sceneClass.prototype || sceneClass.prototype._itOverlayHooked) return;
    sceneClass.prototype._itOverlayHooked = true;
    const _update = sceneClass.prototype.update;
    sceneClass.prototype.update = function() {
      _update.call(this);
      positionUi();
    };
  };

  const _Scene_Boot_start = Scene_Boot.prototype.start;
  Scene_Boot.prototype.start = function() {
    _Scene_Boot_start.call(this);
    ensureUi();
    hookSceneUpdate(Scene_Map);
    hookSceneUpdate(Scene_Battle);
  };
})();
"""


def _overlay_plugin_entry() -> dict[str, Any]:
    return {
        "name": OVERLAY_PLUGIN_NAME,
        "status": True,
        "description": "Interface Tradutores - Overlay de texto para diálogo (MV/MZ)",
        "parameters": {},
    }


def _load_plugins_entries(plugins_js_path: Path) -> list[dict[str, Any]] | None:
    try:
        content = plugins_js_path.read_text(encoding="utf-8-sig", errors="ignore")
    except OSError:
        return None

    match = _PLUGIN_ASSIGN_RE.search(content)
    if not match:
        return None

    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    if not isinstance(parsed, list):
        return None

    result: list[dict[str, Any]] = []
    for item in parsed:
        if isinstance(item, dict):
            result.append(item)
    return result


def _write_plugins_entries(plugins_js_path: Path, entries: list[dict[str, Any]]) -> None:
    plugins_js_path.write_text(
        f"var $plugins = {json.dumps(entries, ensure_ascii=False, indent=2)};\n",
        encoding="utf-8",
    )


def _upsert_overlay_plugin_in_plugins_js(plugins_js_path: Path) -> bool:
    entries = _load_plugins_entries(plugins_js_path)
    if entries is None:
        return False

    found = False
    for item in entries:
        if str(item.get("name", "")).strip() == OVERLAY_PLUGIN_NAME:
            item["status"] = True
            item["description"] = _overlay_plugin_entry()["description"]
            if not isinstance(item.get("parameters"), dict):
                item["parameters"] = {}
            found = True
            break

    if not found:
        entries.append(_overlay_plugin_entry())

    _write_plugins_entries(plugins_js_path, entries)
    return True


def instalar_overlay_rpgm(project_dir: str | Path) -> tuple[bool, str]:
    runtime_root = resolve_rpgm_runtime_root(project_dir)
    if runtime_root is None:
        return (
            False,
            "Overlay RPGM não instalado: não foi possível localizar a raiz de runtime (js/plugins.js).",
        )

    runtime = detectar_runtime_rpgm(project_dir)
    if runtime is None:
        return (
            False,
            "Overlay RPGM não instalado: runtime não reconhecido (esperado MV ou MZ).",
        )

    js_dir = runtime_root / "js"
    plugins_dir = ensure_directory(js_dir / "plugins")
    plugins_js_path = js_dir / "plugins.js"
    if not plugins_js_path.exists() or not plugins_js_path.is_file():
        return (
            False,
            f"Overlay RPGM não instalado: plugins.js não encontrado em {plugins_js_path}.",
        )

    plugin_path = plugins_dir / OVERLAY_PLUGIN_FILENAME
    try:
        plugin_path.write_text(_overlay_plugin_source(), encoding="utf-8")
    except OSError as exc:
        return (False, f"Overlay RPGM não instalado: falha ao gravar plugin JS ({exc}).")

    if not _upsert_overlay_plugin_in_plugins_js(plugins_js_path):
        return (
            False,
            "Overlay RPGM não instalado: não foi possível atualizar js/plugins.js automaticamente.",
        )

    return (True, f"Overlay RPGM instalado/atualizado ({runtime.upper()}) em {plugin_path}.")


def proteger_placeholders(texto: str) -> tuple[str, list[str]]:
    pattern = (
        r"(\\[A-Za-z_]+(?:\[[^\]]+\])?|"
        r"\\[\\><\^._\|!\$\{\}\[\]]|"
        r"[<>].*?[<>])"
    )
    placeholders: list[str] = []

    def repl(match: re.Match[str]) -> str:
        idx = len(placeholders)
        placeholders.append(match.group(0))
        return f"[PLACEHOLDER_{idx}]"

    protegido = re.sub(pattern, repl, texto, flags=re.IGNORECASE)
    return protegido, placeholders


def _looks_like_technical_asset_reference(text: str) -> bool:
    raw = text.strip()
    if not raw:
        return False
    if raw.startswith("!$"):
        return True
    if raw.startswith("$") and " " not in raw and len(raw) > 1:
        return True
    if _URL_RE.search(raw):
        return True
    if _HEX_COLOR_RE.fullmatch(raw):
        return True

    lower = raw.lower()
    if _TECHNICAL_FILE_EXT_RE.search(lower):
        if "/" in raw or "\\" in raw:
            return True
        if re.fullmatch(r"[a-z0-9_.\- ]+", lower):
            return True
    return False


def _is_probably_asset_key(key_name: str | int | None) -> bool:
    if not isinstance(key_name, str):
        return False

    raw_key = key_name.strip()
    key = raw_key.lower()
    if not key:
        return False
    if key in _GENERIC_TECHNICAL_KEYS:
        return True

    # Cobre chaves em camelCase/pascalCase, comuns em plugins.
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", raw_key)
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", expanded).lower()
    parts = [part for part in normalized.split() if part]
    if any(part in _ASSET_KEY_TOKENS for part in parts):
        return True

    # Fallback por substring para casos como "characterName" sem separadores.
    substring_tokens = [
        "image",
        "picture",
        "sprite",
        "icon",
        "face",
        "character",
        "battler",
        "tileset",
        "parallax",
        "background",
        "windowskin",
        "filename",
        "filepath",
        "texture",
        "portrait",
        "bitmap",
        "audio",
        "sound",
        "voice",
        "movie",
        "video",
    ]
    return any(token in key for token in substring_tokens)


def _tokenize_key_name(key_name: str | None) -> list[str]:
    if not key_name:
        return []
    expanded = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", key_name.strip())
    normalized = re.sub(r"[^a-zA-Z0-9]+", " ", expanded).lower()
    return [part for part in normalized.split() if part]


def _resolve_effective_key_name(key_name: str | int | None, path: tuple[Any, ...]) -> str | None:
    if isinstance(key_name, str):
        return key_name

    for token in reversed(path[:-1]):
        if isinstance(token, str):
            return token
    return None


def _is_human_text_key(key_name: str | None) -> bool:
    if not key_name:
        return False
    if _is_probably_asset_key(key_name):
        return False

    key_tokens = _tokenize_key_name(key_name)
    if not key_tokens:
        return False
    if any(token in _GENERIC_BLOCKED_KEY_TOKENS for token in key_tokens):
        return False
    return any(token in _GENERIC_ALLOWED_KEY_TOKENS for token in key_tokens)


def _looks_like_technical_text(text: str) -> bool:
    raw = text.strip()
    if not raw:
        return True
    if _looks_like_technical_asset_reference(raw):
        return True
    if _TECHNICAL_TEXT_RE.search(raw):
        return True
    if re.search(r"[{};=@]", raw):
        return True
    return False


def _is_rpgm_event_parameters_path(path: tuple[Any, ...]) -> bool:
    if len(path) < 8:
        return False
    return (
        path[0] == "events"
        and isinstance(path[1], int)
        and path[2] == "pages"
        and isinstance(path[3], int)
        and path[4] == "list"
        and isinstance(path[5], int)
        and path[6] == "parameters"
    )


def _should_translate_generic_string(
    value: str,
    *,
    key_name: str | int | None,
    path: tuple[Any, ...],
) -> bool:
    text = value.strip()
    if len(text) < 2:
        return False
    if not _HAS_LETTER_RE.search(text):
        return False
    if _is_rpgm_event_parameters_path(path):
        return False
    effective_key = _resolve_effective_key_name(key_name, path)
    if not _is_human_text_key(effective_key):
        return False
    if _looks_like_technical_text(text):
        return False

    return True


def _is_translatable_script_phrase(phrase: str) -> bool:
    text = phrase.strip()
    if len(text) < 3:
        return False
    if text.startswith("$"):
        return False
    if not _HAS_LETTER_RE.search(text):
        return False
    if _looks_like_technical_text(text):
        return False
    if re.fullmatch(r"[A-Za-z0-9_\-]+", text):
        return False
    if text.isupper() and len(text) > 6:
        return False
    if "debug" in text.lower() or "container" in text.lower() or "preset" in text.lower():
        return False
    return True


def _extract_script_phrases(script_text: str) -> list[str]:
    phrases: list[str] = []
    for match in _SCRIPT_PHRASE_RE.finditer(script_text):
        quoted = match.group(1)
        if _is_translatable_script_phrase(quoted):
            phrases.append(quoted)
    return phrases


def _replace_script_phrase_at_index(script_text: str, phrase_index: int, replacement: str) -> str:
    safe_replacement = replacement.replace('"', '\\"')
    current_idx = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal current_idx
        original = match.group(1)
        if not _is_translatable_script_phrase(original):
            return match.group(0)

        if current_idx == phrase_index:
            current_idx += 1
            return f'"{safe_replacement}"'

        current_idx += 1
        return match.group(0)

    return _SCRIPT_PHRASE_RE.sub(repl, script_text)


def _add_value_target(
    targets: list[_TextTarget],
    covered_paths: set[tuple[Any, ...]],
    container: Any,
    key: Any,
    path: tuple[Any, ...],
    *,
    wrap_dialogue: bool = False,
) -> None:
    if isinstance(container, dict):
        value = container.get(key)
    elif isinstance(container, list) and isinstance(key, int) and 0 <= key < len(container):
        value = container[key]
    else:
        return

    if not isinstance(value, str) or not value.strip():
        return

    protected, placeholders = proteger_placeholders(value)

    def apply_value(translated: str, *, holder: Any = container, holder_key: Any = key) -> None:
        final_text = wrap_dialogue_text_for_rpgm(translated) if wrap_dialogue else translated
        if isinstance(holder, dict):
            holder[holder_key] = final_text
        elif isinstance(holder, list) and isinstance(holder_key, int) and 0 <= holder_key < len(holder):
            holder[holder_key] = final_text

    targets.append(
        _TextTarget(
            protected_text=protected,
            placeholders=placeholders,
            apply=apply_value,
        )
    )
    covered_paths.add(path)


def _collect_structured_targets(data: Any) -> tuple[list[_TextTarget], set[tuple[Any, ...]], set[tuple[Any, ...]]]:
    targets: list[_TextTarget] = []
    covered_paths: set[tuple[Any, ...]] = set()
    script_source_paths: set[tuple[Any, ...]] = set()

    if isinstance(data, list):
        for item_idx, item in enumerate(data):
            if not isinstance(item, dict):
                continue
            if "name" in item and isinstance(item.get("name"), str) and item["name"].strip():
                _add_value_target(targets, covered_paths, item, "name", (item_idx, "name"))
            if (
                "description" in item
                and isinstance(item.get("description"), str)
                and item["description"].strip()
            ):
                _add_value_target(
                    targets,
                    covered_paths,
                    item,
                    "description",
                    (item_idx, "description"),
                )

    if isinstance(data, dict):
        events = data.get("events", [])
        if isinstance(events, list):
            for event_idx, event in enumerate(events):
                if not isinstance(event, dict):
                    continue

                pages = event.get("pages", [])
                if not isinstance(pages, list):
                    continue

                for page_idx, page in enumerate(pages):
                    if not isinstance(page, dict):
                        continue

                    commands = page.get("list", [])
                    if not isinstance(commands, list):
                        continue

                    for command_idx, cmd in enumerate(commands):
                        if not isinstance(cmd, dict):
                            continue

                        code = cmd.get("code")
                        params = cmd.get("parameters")
                        if not isinstance(params, list) or not params:
                            continue

                        cmd_path = ("events", event_idx, "pages", page_idx, "list", command_idx)

                        if code in [401, 405] and len(params) > 0 and isinstance(params[0], str):
                            _add_value_target(
                                targets,
                                covered_paths,
                                params,
                                0,
                                (*cmd_path, "parameters", 0),
                                wrap_dialogue=True,
                            )
                        elif code == 102 and len(params) > 0 and isinstance(params[0], list):
                            for choice_idx, choice in enumerate(params[0]):
                                if not isinstance(choice, str):
                                    continue
                                _add_value_target(
                                    targets,
                                    covered_paths,
                                    params[0],
                                    choice_idx,
                                    (*cmd_path, "parameters", 0, choice_idx),
                                    wrap_dialogue=True,
                                )
                        elif code == 402 and len(params) > 1 and isinstance(params[1], str):
                            _add_value_target(
                                targets,
                                covered_paths,
                                params,
                                1,
                                (*cmd_path, "parameters", 1),
                                wrap_dialogue=True,
                            )
                        elif code in [355, 655] and len(params) > 0 and isinstance(params[0], str):
                            script_text = params[0]
                            phrases = _extract_script_phrases(script_text)
                            if not phrases:
                                continue

                            script_path = (*cmd_path, "parameters", 0)
                            script_source_paths.add(script_path)

                            for phrase_idx, phrase in enumerate(phrases):
                                protected, placeholders = proteger_placeholders(phrase)

                                def apply_script(
                                    translated: str,
                                    *,
                                    holder: list[Any] = params,
                                    target_phrase_idx: int = phrase_idx,
                                ) -> None:
                                    if not holder or not isinstance(holder[0], str):
                                        return
                                    holder[0] = _replace_script_phrase_at_index(
                                        str(holder[0]), target_phrase_idx, translated
                                    )

                                targets.append(
                                    _TextTarget(
                                        protected_text=protected,
                                        placeholders=placeholders,
                                        apply=apply_script,
                                    )
                                )

    return targets, covered_paths, script_source_paths


def _collect_generic_targets(
    data: Any,
    targets: list[_TextTarget],
    covered_paths: set[tuple[Any, ...]],
    script_source_paths: set[tuple[Any, ...]],
) -> None:
    def walk(node: Any, *, parent: Any, key: Any, path: tuple[Any, ...]) -> None:
        if isinstance(node, dict):
            for child_key, child_value in node.items():
                walk(child_value, parent=node, key=child_key, path=(*path, child_key))
            return

        if isinstance(node, list):
            for idx, child_value in enumerate(node):
                walk(child_value, parent=node, key=idx, path=(*path, idx))
            return

        if not isinstance(node, str):
            return
        if path in covered_paths or path in script_source_paths:
            return
        if not _should_translate_generic_string(node, key_name=key, path=path):
            return

        protected, placeholders = proteger_placeholders(node)

        def apply_generic(
            translated: str,
            *,
            holder: Any = parent,
            holder_key: Any = key,
        ) -> None:
            if isinstance(holder, dict):
                holder[holder_key] = translated
            elif isinstance(holder, list) and isinstance(holder_key, int) and 0 <= holder_key < len(holder):
                holder[holder_key] = translated

        targets.append(
            _TextTarget(
                protected_text=protected,
                placeholders=placeholders,
                apply=apply_generic,
            )
        )
        covered_paths.add(path)

    if isinstance(data, dict):
        for top_key, top_value in data.items():
            walk(top_value, parent=data, key=top_key, path=(top_key,))
    elif isinstance(data, list):
        for idx, top_value in enumerate(data):
            walk(top_value, parent=data, key=idx, path=(idx,))


def _collect_text_targets(data: Any) -> list[_TextTarget]:
    targets, covered_paths, script_source_paths = _collect_structured_targets(data)
    _collect_generic_targets(data, targets, covered_paths, script_source_paths)
    return targets


def extrair_textos_json(caminho: Path) -> tuple[list[str], list[list[str]]]:
    with caminho.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            return [], []

    targets = _collect_text_targets(data)
    textos = [target.protected_text for target in targets]
    placeholders_list = [target.placeholders for target in targets]
    return textos, placeholders_list


def carregar_dados_globais(nome_txt: str | Path) -> dict[str, list[str]]:
    mapa: dict[str, list[str]] = {}
    path = Path(nome_txt)
    if not path.exists():
        return mapa

    with path.open("r", encoding="utf-8") as f:
        content = f.read().replace("\r\n", "\n").replace("\r", "\n")

    partes = [sec for sec in content.split("=== ") if sec.strip()]
    for sec in partes:
        if " ===\n" not in sec:
            continue
        filename, body = sec.split(" ===\n", 1)
        filename = filename.strip()
        linhas = body.split("\n")
        while linhas and linhas[-1] == "":
            linhas.pop()
        mapa[filename] = linhas
    return mapa


def carregar_placeholders(nome_ph: str | Path) -> dict[str, list[list[str]]]:
    mapa: dict[str, list[list[str]]] = {}
    path = Path(nome_ph)
    if not path.exists():
        return mapa

    with path.open("r", encoding="utf-8") as f:
        content = f.read().replace("\r\n", "\n").replace("\r", "\n")

    partes = [sec for sec in content.split("=== ") if sec.strip()]
    for sec in partes:
        if " ===\n" not in sec:
            continue
        filename, body = sec.split(" ===\n", 1)
        filename = filename.strip()
        linhas = body.split("\n")
        while linhas and linhas[-1] == "":
            linhas.pop()

        lista_phs: list[list[str]] = []
        for l in linhas:
            if l.strip() == "":
                lista_phs.append([])
            else:
                lista_phs.append(l.strip().split("|||"))
        mapa[filename] = lista_phs
    return mapa


def restaurar_placeholders(text: str, phs: list[str]) -> str:
    for i, ph in enumerate(phs):
        text = text.replace(f"[PLACEHOLDER_{i}]", ph)
    return text


def _wrap_dialogue_segment(segment: str, limit: int = RPGM_DIALOGUE_WRAP_LIMIT) -> str:
    if not segment or len(segment) <= limit:
        return segment

    protected, placeholders = proteger_placeholders(segment)
    parts = re.split(r"(\s+)", protected)

    lines: list[str] = []
    current = ""

    for part in parts:
        if part == "":
            continue

        candidate = f"{current}{part}" if current else part
        if current and not part.isspace() and len(candidate) > limit:
            lines.append(current.rstrip())
            current = part.lstrip()
        else:
            current = candidate

    if current.strip():
        lines.append(current.rstrip())

    if not lines:
        return segment

    # Evita a quebra "feia" quando sobra uma palavra muito curta na última linha.
    if len(lines) >= 2 and len(lines[-1].strip()) <= 10:
        previous = lines[-2].rstrip()
        tail = lines[-1].lstrip()
        if len(f"{previous} {tail}".strip()) <= limit + 12:
            lines[-2] = f"{previous} {tail}".strip()
            lines.pop()

    restored_lines = [restaurar_placeholders(line, placeholders) for line in lines]
    return "\n".join(restored_lines)


def wrap_dialogue_text_for_rpgm(text: str, limit: int = RPGM_DIALOGUE_WRAP_LIMIT) -> str:
    if not text or len(text) <= limit:
        return text

    chunks = text.split("\n")
    wrapped_chunks = [_wrap_dialogue_segment(chunk, limit=limit) for chunk in chunks]
    return "\n".join(wrapped_chunks)


def reintegrar_json(
    caminho: Path,
    traducoes: list[str],
    ph_map: list[list[str]],
    log: TextIO,
    *,
    display_name: str | None = None,
) -> None:
    name = display_name or caminho.name
    with caminho.open("r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError:
            log.write(f"[ERRO] {name} não é um JSON válido.\n")
            return

    targets = _collect_text_targets(data)
    total_targets = len(targets)
    total_translations = len(traducoes)
    applied_count = 0

    for idx, target in enumerate(targets):
        if idx >= total_translations:
            break

        translated = traducoes[idx]
        tags = ph_map[idx] if idx < len(ph_map) else []
        restored = restaurar_placeholders(translated, tags)

        if "[PLACEHOLDER_" in restored:
            log.write(f"[FALHA DE TAG] {name} | idx {idx}\n")

        target.apply(restored)
        applied_count += 1

    if total_translations > total_targets:
        log.write(
            f"[ALERTA] {name} recebeu {total_translations - total_targets} linhas extras sem alvo de aplicação.\n"
        )
    elif total_targets > total_translations:
        log.write(
            f"[ALERTA] {name} possui {total_targets - total_translations} textos sem tradução correspondente.\n"
        )

    with caminho.open("w", encoding="utf-8") as f:
        json.dump(data, f, separators=(",", ":"), ensure_ascii=False)

    log.write(
        f"[OK] {name} processado. ({applied_count}/{total_translations} traduções aplicadas; "
        f"{total_targets} alvos encontrados)\n"
    )


def _find_recursive_name_matches(data_dir: Path, filename: str) -> list[Path]:
    lowered = filename.lower()
    return sorted(
        [
            path
            for path in data_dir.rglob(filename)
            if path.is_file() and path.name.lower() == lowered
        ],
        key=lambda p: p.relative_to(data_dir).as_posix().lower(),
    )


def _resolve_rpgm_mapped_file(data_dir: Path, stored_path: str) -> tuple[Path | None, str | None]:
    normalized = str(stored_path or "").replace("\\", "/").strip().lstrip("/")
    if not normalized:
        return None, "Entrada vazia no mapa de arquivos RPGM."

    candidate = data_dir / Path(normalized)
    if candidate.exists() and candidate.is_file():
        return candidate, None

    original_had_separator = "/" in normalized
    filename = Path(normalized).name
    if original_had_separator:
        return None, None

    root_candidate = data_dir / filename
    if root_candidate.exists() and root_candidate.is_file():
        return root_candidate, None

    matches = _find_recursive_name_matches(data_dir, filename)
    if len(matches) == 1:
        return matches[0], None
    if len(matches) > 1:
        return (
            None,
            f"Mapa legado ambíguo para '{filename}': múltiplos arquivos encontrados na pasta de dados RPGM.",
        )

    return None, None


def exportar_rpgm(project_dir: str | Path, workspace_dir: str | Path) -> JobResult:
    project = Path(project_dir)
    workspace = ensure_directory(workspace_dir)

    if not project.exists():
        return JobResult(success=False, message=f"Pasta não encontrada: {project}")

    data_dir = resolve_rpgm_data_dir(project)
    if data_dir is None:
        return JobResult(
            success=False,
            message="Nenhum arquivo .json de RPGM encontrado em www/data, data ou na pasta selecionada.",
        )

    arquivos_json = _iter_rpgm_json_files(data_dir)
    if not arquivos_json:
        return JobResult(
            success=False,
            message="Nenhum arquivo .json de RPGM encontrado na pasta selecionada.",
        )

    dict_txt: dict[str, list[str]] = {}
    dict_placeh: dict[str, list[list[str]]] = {}
    for caminho in arquivos_json:
        textos, phs_list = extrair_textos_json(caminho)
        if textos:
            relative_key = caminho.relative_to(data_dir).as_posix()
            dict_txt[relative_key] = textos
            dict_placeh[relative_key] = phs_list

    mapa_arquivos: dict[str, str] = {}
    translations_path = workspace / TRANSLATIONS_FILENAME
    placeholders_path = workspace / PLACEHOLDERS_FILENAME
    map_path = workspace / MAP_FILENAME

    with translations_path.open("w", encoding="utf-8") as f_txt, placeholders_path.open(
        "w", encoding="utf-8"
    ) as f_ph:
        for i, (arq, textos) in enumerate(dict_txt.items()):
            chave_arquivo = f"ARQUIVO_{i:03d}"
            mapa_arquivos[chave_arquivo] = arq

            f_txt.write(f"=== {chave_arquivo} ===\n")
            for t in textos:
                f_txt.write(t + "\n")
            f_txt.write("\n")

            f_ph.write(f"=== {chave_arquivo} ===\n")
            for phs in dict_placeh[arq]:
                f_ph.write("|||".join(phs) + "\n")
            f_ph.write("\n")

    with map_path.open("w", encoding="utf-8") as f_map:
        json.dump(mapa_arquivos, f_map, indent=4, ensure_ascii=False)

    data_desc = describe_rpgm_data_dir(project, data_dir)
    return JobResult(
        success=True,
        message=f"Exportação RPGM concluída ({len(dict_txt)} arquivos). Pasta de dados usada: {data_desc}.",
        generated_files=[str(translations_path), str(placeholders_path), str(map_path)],
    )


def importar_rpgm(
    project_dir: str | Path,
    workspace_dir: str | Path,
    translated_txt_path: str | Path,
    criar_backup: bool = False,
) -> JobResult:
    project = Path(project_dir)
    workspace = ensure_directory(workspace_dir)
    translated_path = Path(translated_txt_path)
    placeholders_path = workspace / PLACEHOLDERS_FILENAME
    map_path = workspace / MAP_FILENAME
    log_path = workspace / IMPORT_LOG_FILENAME

    data_dir = resolve_rpgm_data_dir(project)
    if data_dir is None:
        return JobResult(
            success=False,
            message="Nenhum arquivo .json de RPGM encontrado em www/data, data ou na pasta selecionada.",
        )

    if not translated_path.exists():
        return JobResult(success=False, message=f"Arquivo traduzido não encontrado: {translated_path}")
    if not placeholders_path.exists():
        return JobResult(success=False, message=f"Arquivo não encontrado: {placeholders_path}")
    if not map_path.exists():
        return JobResult(success=False, message=f"Arquivo não encontrado: {map_path}")

    t_map = carregar_dados_globais(translated_path)
    p_map = carregar_placeholders(placeholders_path)

    with map_path.open("r", encoding="utf-8") as f_map:
        mapa_arquivos: dict[str, str] = json.load(f_map)

    warnings: list[str] = []
    resolved_targets: dict[str, Path] = {}
    resolution_warnings_by_key: dict[str, str] = {}
    for chave_arquivo, arq_original in mapa_arquivos.items():
        if chave_arquivo not in t_map:
            continue
        resolved_path, resolve_warning = _resolve_rpgm_mapped_file(data_dir, arq_original)
        if resolve_warning:
            resolution_warnings_by_key[chave_arquivo] = resolve_warning
        if resolved_path is not None:
            resolved_targets[chave_arquivo] = resolved_path

    backup_dir: Path | None = None
    if criar_backup and resolved_targets:
        unique_targets = sorted(
            {path.resolve() for path in resolved_targets.values()},
            key=lambda p: str(p).lower(),
        )
        backup_dir = create_backup_snapshot("rpgm", project, workspace, unique_targets)

    data_desc = describe_rpgm_data_dir(project, data_dir)
    with log_path.open("w", encoding="utf-8") as log:
        for chave_arquivo, arq_original in mapa_arquivos.items():
            if chave_arquivo not in t_map:
                continue

            warning_for_key = resolution_warnings_by_key.get(chave_arquivo)
            if warning_for_key:
                warning = warning_for_key
                warnings.append(warning)
                log.write(f"[AVISO] {warning}\n")

            caminho = resolved_targets.get(chave_arquivo)
            if caminho is not None:
                phs = p_map.get(chave_arquivo, [])
                if len(t_map[chave_arquivo]) != len(phs):
                    alerta = (
                        f"{arq_original}: {len(t_map[chave_arquivo])} traduções vs {len(phs)} placeholders."
                    )
                    warnings.append(alerta)
                    log.write(f"[ALERTA DE DESVIO] {alerta}\n")
                reintegrar_json(
                    caminho,
                    t_map[chave_arquivo],
                    phs,
                    log,
                    display_name=arq_original,
                )
            else:
                if warning_for_key and "ambíguo" in warning_for_key:
                    continue
                if "/" not in str(arq_original) and "\\" not in str(arq_original):
                    aviso = (
                        f"Arquivo {arq_original} não encontrado na pasta de dados RPGM ({data_desc})."
                    )
                else:
                    aviso = (
                        f"Arquivo {arq_original} não encontrado dentro da pasta de dados RPGM ({data_desc})."
                    )
                warnings.append(aviso)
                log.write(f"[AVISO] {aviso}\n")

        overlay_ok, overlay_message = instalar_overlay_rpgm(project)
        if overlay_ok:
            log.write(f"[OK] {overlay_message}\n")
        else:
            warnings.append(overlay_message)
            log.write(f"[AVISO] {overlay_message}\n")

    message = f"Importação RPGM concluída. Pasta de dados usada: {data_desc}."
    if backup_dir:
        message += f" Backup criado em: {backup_dir}"
    if overlay_ok:
        message += " Overlay RPGM instalado."

    return JobResult(
        success=True,
        message=message,
        warnings=warnings,
        generated_files=[str(log_path)],
        log_file=str(log_path),
    )


def parse_json_safely(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return None
