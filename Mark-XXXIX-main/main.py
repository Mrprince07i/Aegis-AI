import asyncio
import os
import re
import threading
import json
import sys
import math
import traceback
from pathlib import Path


import sounddevice as sd
from google import genai
from google.genai import types
from ui import AegisUI
import updater
from memory.memory_manager import (
    load_memory, update_memory, format_memory_for_prompt, recall_memory,
)

from actions.file_processor import file_processor
from actions.flight_finder     import flight_finder
from actions.open_app          import open_app
from actions.weather_report    import weather_action
from actions.send_message      import send_message
from actions.reminder          import reminder
from actions.computer_settings import computer_settings
from actions.screen_processor  import screen_process
from actions.youtube_video     import youtube_video
from actions.desktop           import desktop_control
from actions.browser_control   import browser_control
from actions.file_controller   import file_controller
from actions.code_helper       import code_helper
from actions.dev_agent         import dev_agent
from actions.web_search        import web_search as web_search_action
from actions.computer_control  import computer_control
from actions.game_updater      import game_updater
from actions.study_explainer   import study_explainer
from actions.calendar_manager  import calendar_manager
from actions.notes_manager     import notes_manager
from actions.task_manager      import task_manager
from actions.focus_timer       import focus_timer
from actions.predictive_suggest import predictive_suggest


def get_base_dir():
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent


BASE_DIR        = get_base_dir()
API_CONFIG_PATH = BASE_DIR / "config" / "api_keys.json"
PROMPT_PATH     = BASE_DIR / "core" / "prompt.txt"
LIVE_MODEL          = "models/gemini-2.5-flash-native-audio-preview-12-2025"
CHANNELS            = 1
SEND_SAMPLE_RATE    = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE          = 1024

def _get_api_key() -> str:
    with open(API_CONFIG_PATH, "r", encoding="utf-8") as f:
        return json.load(f)["gemini_api_key"]


def _load_system_prompt() -> str:
    try:
        return PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        return (
            "You are Aegis, a cutting-edge personal AI assistant. "
            "Be concise, direct, and always use the provided tools to complete tasks. "
            "Never simulate or guess results \u2014 always call the appropriate tool. "

        )

_CTRL_RE = re.compile(r"<ctrl\d+>", re.IGNORECASE)

def _clean_transcript(text: str) -> str:    
    text = _CTRL_RE.sub("", text)
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", text)
    return text.strip()

TOOL_DECLARATIONS = [
    {
        "name": "open_app",
        "description": (
            "Opens any application on the computer. "
            "Use this whenever the user asks to open, launch, or start any app, "
            "website, or program. Always call this tool � never just say you opened it."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "app_name": {
                    "type": "STRING",
                    "description": "Exact name of the application (e.g. 'WhatsApp', 'Chrome', 'Spotify')"
                }
            },
            "required": ["app_name"]
        }
    },
    {
        "name": "web_search",
        "description": "Searches the web for any information.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query":  {"type": "STRING", "description": "Search query"},
                "mode":   {"type": "STRING", "description": "search (default) or compare"},
                "items":  {"type": "ARRAY", "items": {"type": "STRING"}, "description": "Items to compare"},
                "aspect": {"type": "STRING", "description": "price | specs | reviews"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "weather_report",
        "description": "Gives the weather report to user",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "city": {"type": "STRING", "description": "City name"}
            },
            "required": ["city"]
        }
    },
    {
        "name": "send_message",
        "description": "Sends a text message via WhatsApp, Telegram, or other messaging platform.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "receiver":     {"type": "STRING", "description": "Recipient contact name"},
                "message_text": {"type": "STRING", "description": "The message to send"},
                "platform":     {"type": "STRING", "description": "Platform: WhatsApp, Telegram, etc."}
            },
            "required": ["receiver", "message_text", "platform"]
        }
    },
    {
        "name": "reminder",
        "description": "Sets a timed reminder using Task Scheduler.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "date":    {"type": "STRING", "description": "Date in YYYY-MM-DD format"},
                "time":    {"type": "STRING", "description": "Time in HH:MM format (24h)"},
                "message": {"type": "STRING", "description": "Reminder message text"}
            },
            "required": ["date", "time", "message"]
        }
    },
    {
        "name": "youtube_video",
        "description": (
            "Controls YouTube. Use for: playing videos, summarizing a video's content, "
            "getting video info, or showing trending videos."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "play | summarize | get_info | trending (default: play)"},
                "query":  {"type": "STRING", "description": "Search query for play action"},
                "save":   {"type": "BOOLEAN", "description": "Save summary to Notepad (summarize only)"},
                "region": {"type": "STRING", "description": "Country code for trending e.g. TR, US"},
                "url":    {"type": "STRING", "description": "Video URL for get_info action"},
            },
            "required": []
        }
    },
    {
        "name": "screen_process",
        "description": (
            "Captures and analyzes the screen or webcam image. "
            "MUST be called when user asks what is on screen, what you see, "
            "analyze my screen, look at camera, etc. "
            "You have NO visual ability without this tool. "
            "After calling this tool, stay SILENT — the vision module speaks directly."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "angle": {"type": "STRING", "description": "'screen' to capture display, 'camera' for webcam. Default: 'screen'"},
                "text":  {"type": "STRING", "description": "The question or instruction about the captured image"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "computer_settings",
        "description": (
            "Controls the computer: volume, brightness, window management, keyboard shortcuts, "
            "typing text on screen, closing apps, fullscreen, dark mode, WiFi, restart, shutdown, "
            "scrolling, tab management, zoom, screenshots, lock screen, refresh/reload page. "
            "Use for ANY single computer control command. NEVER route to agent_task."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "The action to perform"},
                "description": {"type": "STRING", "description": "Natural language description of what to do"},
                "value":       {"type": "STRING", "description": "Optional value: volume level, text to type, etc."}
            },
            "required": []
        }
    },
    {
        "name": "browser_control",
        "description": (
            "Controls any web browser. Use for: opening websites, searching the web, "
            "clicking elements, filling forms, scrolling, screenshots, navigation, any web-based task. "
            "Always pass the 'browser' parameter when the user specifies a browser (e.g. 'open in Edge', "
            "'use Firefox', 'open Chrome'). Multiple browsers can run simultaneously."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "go_to | search | click | type | scroll | fill_form | smart_click | smart_type | get_text | get_url | press | new_tab | close_tab | screenshot | back | forward | reload | switch | list_browsers | close | close_all"},
                "browser":     {"type": "STRING", "description": "Target browser: chrome | edge | firefox | opera | operagx | brave | vivaldi | safari. Omit to use the currently active browser."},
                "url":         {"type": "STRING", "description": "URL for go_to / new_tab action"},
                "query":       {"type": "STRING", "description": "Search query for search action"},
                "engine":      {"type": "STRING", "description": "Search engine: google | bing | duckduckgo | yandex (default: google)"},
                "selector":    {"type": "STRING", "description": "CSS selector for click/type"},
                "text":        {"type": "STRING", "description": "Text to click or type"},
                "description": {"type": "STRING", "description": "Element description for smart_click/smart_type"},
                "direction":   {"type": "STRING", "description": "up | down for scroll"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount in pixels (default: 500)"},
                "key":         {"type": "STRING", "description": "Key name for press action (e.g. Enter, Escape, F5)"},
                "path":        {"type": "STRING", "description": "Save path for screenshot"},
                "incognito":   {"type": "BOOLEAN", "description": "Open in private/incognito mode"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "file_controller",
        "description": "Manages files and folders: list, create, delete, move, copy, rename, read, write, find, disk usage.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "list | create_file | create_folder | delete | move | copy | rename | read | write | find | largest | disk_usage | organize_desktop | info"},
                "path":        {"type": "STRING", "description": "File/folder path or shortcut: desktop, downloads, documents, home"},
                "destination": {"type": "STRING", "description": "Destination path for move/copy"},
                "new_name":    {"type": "STRING", "description": "New name for rename"},
                "content":     {"type": "STRING", "description": "Content for create_file/write"},
                "name":        {"type": "STRING", "description": "File name to search for"},
                "extension":   {"type": "STRING", "description": "File extension to search (e.g. .pdf)"},
                "count":       {"type": "INTEGER", "description": "Number of results for largest"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "desktop_control",
        "description": "Controls the desktop: wallpaper, organize, clean, list, stats.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action": {"type": "STRING", "description": "wallpaper | wallpaper_url | organize | clean | list | stats | task"},
                "path":   {"type": "STRING", "description": "Image path for wallpaper"},
                "url":    {"type": "STRING", "description": "Image URL for wallpaper_url"},
                "mode":   {"type": "STRING", "description": "by_type or by_date for organize"},
                "task":   {"type": "STRING", "description": "Natural language desktop task"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "code_helper",
        "description": "Writes, edits, explains, runs, or builds code files.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "write | edit | explain | run | build | auto (default: auto)"},
                "description": {"type": "STRING", "description": "What the code should do or what change to make"},
                "language":    {"type": "STRING", "description": "Programming language (default: python)"},
                "output_path": {"type": "STRING", "description": "Where to save the file"},
                "file_path":   {"type": "STRING", "description": "Path to existing file for edit/explain/run/build"},
                "code":        {"type": "STRING", "description": "Raw code string for explain"},
                "args":        {"type": "STRING", "description": "CLI arguments for run/build"},
                "timeout":     {"type": "INTEGER", "description": "Execution timeout in seconds (default: 30)"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "dev_agent",
        "description": "Builds complete multi-file projects from scratch: plans, writes files, installs deps, opens VSCode, runs and fixes errors.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "description":  {"type": "STRING", "description": "What the project should do"},
                "language":     {"type": "STRING", "description": "Programming language (default: python)"},
                "project_name": {"type": "STRING", "description": "Optional project folder name"},
                "timeout":      {"type": "INTEGER", "description": "Run timeout in seconds (default: 30)"},
            },
            "required": ["description"]
        }
    },
    {
        "name": "agent_task",
        "description": (
            "Legacy simple task executor for basic multi-step tasks. "
            "For COMPLEX tasks requiring research, memory, planning, or multiple specialized capabilities, "
            "use 'agent_delegate' instead."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal":     {"type": "STRING", "description": "Complete description of what to accomplish"},
                "priority": {"type": "STRING", "description": "low | normal | high (default: normal)"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "agent_delegate",
        "description": (
            "THE PRIMARY tool for complex or hard tasks. Delegates to 6 specialized agents "
            "(Target, Logic, Knowledge, Brain, Executor, Validator) who work together "
            "to accomplish the goal. Use for: research, analysis, multi-step workflows, "
            "creative tasks, problem-solving. Do NOT use for simple single-command tasks."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "goal": {"type": "STRING", "description": "Complete task description of what to accomplish"}
            },
            "required": ["goal"]
        }
    },
    {
        "name": "computer_control",
        "description": "Direct computer control: type, click, hotkeys, scroll, move mouse, screenshots, find elements on screen.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":      {"type": "STRING", "description": "type | smart_type | click | double_click | right_click | hotkey | press | scroll | move | copy | paste | screenshot | wait | clear_field | focus_window | screen_find | screen_click | random_data | user_data"},
                "text":        {"type": "STRING", "description": "Text to type or paste"},
                "x":           {"type": "INTEGER", "description": "X coordinate"},
                "y":           {"type": "INTEGER", "description": "Y coordinate"},
                "keys":        {"type": "STRING", "description": "Key combination e.g. 'ctrl+c'"},
                "key":         {"type": "STRING", "description": "Single key e.g. 'enter'"},
                "direction":   {"type": "STRING", "description": "up | down | left | right"},
                "amount":      {"type": "INTEGER", "description": "Scroll amount (default: 3)"},
                "seconds":     {"type": "NUMBER",  "description": "Seconds to wait"},
                "title":       {"type": "STRING",  "description": "Window title for focus_window"},
                "description": {"type": "STRING",  "description": "Element description for screen_find/screen_click"},
                "type":        {"type": "STRING",  "description": "Data type for random_data"},
                "field":       {"type": "STRING",  "description": "Field for user_data: name|email|city"},
                "clear_first": {"type": "BOOLEAN", "description": "Clear field before typing (default: true)"},
                "path":        {"type": "STRING",  "description": "Save path for screenshot"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "game_updater",
        "description": (
            "THE ONLY tool for ANY Steam or Epic Games request. "
            "Use for: installing, downloading, updating games, listing installed games, "
            "checking download status, scheduling updates. "
            "ALWAYS call directly for any Steam/Epic/game request. "
            "NEVER use agent_task, browser_control, or web_search for Steam/Epic."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":    {"type": "STRING",  "description": "update | install | list | download_status | schedule | cancel_schedule | schedule_status (default: update)"},
                "platform":  {"type": "STRING",  "description": "steam | epic | both (default: both)"},
                "game_name": {"type": "STRING",  "description": "Game name (partial match supported)"},
                "app_id":    {"type": "STRING",  "description": "Steam AppID for install (optional)"},
                "hour":      {"type": "INTEGER", "description": "Hour for scheduled update 0-23 (default: 3)"},
                "minute":    {"type": "INTEGER", "description": "Minute for scheduled update 0-59 (default: 0)"},
                "shutdown_when_done": {"type": "BOOLEAN", "description": "Shut down PC when download finishes"},
            },
            "required": []
        }
    },
    {
        "name": "flight_finder",
        "description": "Searches Google Flights and speaks the best options.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "origin":      {"type": "STRING",  "description": "Departure city or airport code"},
                "destination": {"type": "STRING",  "description": "Arrival city or airport code"},
                "date":        {"type": "STRING",  "description": "Departure date (any format)"},
                "return_date": {"type": "STRING",  "description": "Return date for round trips"},
                "passengers":  {"type": "INTEGER", "description": "Number of passengers (default: 1)"},
                "cabin":       {"type": "STRING",  "description": "economy | premium | business | first"},
                "save":        {"type": "BOOLEAN", "description": "Save results to Notepad"},
            },
            "required": ["origin", "destination", "date"]
        }
    },
    {
        "name": "shutdown_aegis",
        "description": (
            "Shuts down the assistant completely. "
            "Call this when the user expresses intent to end the conversation, "
            "close the assistant, say goodbye, or stop Aegis. "
            "The user can say this in ANY language."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
        }
    },
    {
    "name": "file_processor",
    "description": (
        "Processes any file that the user has uploaded or dropped onto the interface. "
        "Use this when the user refers to an uploaded file and wants an action on it. "
        "Supports: images (describe/ocr/resize/compress/convert), "
        "PDFs (summarize/extract_text/to_word), "
        "Word docs & text files (summarize/fix/reformat/translate), "
        "CSV/Excel (analyze/stats/filter/sort/convert), "
        "JSON/XML (validate/format/analyze), "
        "code files (explain/review/fix/optimize/run/document/test), "
        "audio (transcribe/trim/convert/info), "
        "video (trim/extract_audio/extract_frame/compress/transcribe/info), "
        "archives (list/extract), "
        "presentations (summarize/extract_text). "
        "ALWAYS call this tool when a file has been uploaded and the user gives a command about it. "
        "If the user's command is ambiguous, pick the most logical action for that file type."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "file_path": {
                "type": "STRING",
                "description": "Full path to the uploaded file. Leave empty to use the currently uploaded file."
            },
            "action": {
                "type": "STRING",
                "description": (
                    "What to do with the file. Examples by type:\n"
                    "image: describe | ocr | resize | compress | convert | info\n"
                    "pdf: summarize | extract_text | to_word | info\n"
                    "docx/txt: summarize | fix | reformat | translate_hint | word_count | to_bullet\n"
                    "csv/excel: analyze | stats | filter | sort | convert | info\n"
                    "json: validate | format | analyze | to_csv\n"
                    "code: explain | review | fix | optimize | run | document | test\n"
                    "audio: transcribe | trim | convert | info\n"
                    "video: trim | extract_audio | extract_frame | compress | transcribe | info | convert\n"
                    "archive: list | extract\n"
                    "pptx: summarize | extract_text | analyze"
                )
            },
            "instruction": {
                "type": "STRING",
                "description": "Free-form instruction if action doesn't cover it. E.g. 'translate this to Turkish', 'find all email addresses'"
            },
            "format": {
                "type": "STRING",
                "description": "Target format for conversion. E.g. 'mp3', 'pdf', 'csv', 'png'"
            },
            "width":     {"type": "INTEGER", "description": "Target width for image resize"},
            "height":    {"type": "INTEGER", "description": "Target height for image resize"},
            "scale":     {"type": "NUMBER",  "description": "Scale factor for image resize (e.g. 0.5)"},
            "quality":   {"type": "INTEGER", "description": "Quality 1-100 for image/video compress"},
            "start":     {"type": "STRING",  "description": "Start time for trim: seconds or HH:MM:SS"},
            "end":       {"type": "STRING",  "description": "End time for trim: seconds or HH:MM:SS"},
            "timestamp": {"type": "STRING",  "description": "Timestamp for video frame extraction HH:MM:SS"},
            "column":    {"type": "STRING",  "description": "Column name for CSV filter/sort"},
            "value":     {"type": "STRING",  "description": "Filter value for CSV filter"},
            "condition": {"type": "STRING",  "description": "Filter condition: equals|contains|gt|lt"},
            "ascending": {"type": "BOOLEAN", "description": "Sort order for CSV sort (default: true)"},
            "save":      {"type": "BOOLEAN", "description": "Save result to file (default: true)"},
            "destination": {"type": "STRING", "description": "Output folder for archive extract"},
        },
        "required": []
    }
},
    {
        "name": "calendar_manager",
        "description": (
            "Manages the user's personal schedule and calendar events. "
            "Use for: adding events/meetings/tasks, viewing today's schedule, "
            "listing upcoming events, or deleting events. "
            "Always call this for any scheduling or calendar request."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":  {"type": "STRING", "description": "add | view | today | list | delete | upcoming"},
                "title":   {"type": "STRING", "description": "Event title (for add/delete)"},
                "date":    {"type": "STRING", "description": "Date: today, tomorrow, YYYY-MM-DD, etc."},
                "time":    {"type": "STRING", "description": "Time in HH:MM or natural (e.g. 5pm, 14:30)"},
                "note":    {"type": "STRING", "description": "Optional extra note for the event"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "notes_manager",
        "description": (
            "Saves and retrieves voice notes and journal entries. "
            "Use for: saving any note/idea/todo the user speaks, "
            "viewing all notes, searching notes, or deleting notes. "
            "Auto-categorizes into: general, study, idea, todo, work, personal."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING", "description": "add | view | search | list | delete"},
                "title":    {"type": "STRING", "description": "Note title (optional, auto-generated if missing)"},
                "body":     {"type": "STRING", "description": "The actual note content to save"},
                "category": {"type": "STRING", "description": "general | study | idea | todo | work | personal"},
                "query":    {"type": "STRING", "description": "Search keyword for search action"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "task_manager",
        "description": (
            "Manages the user's personal task / todo list. "
            "Use for: adding new tasks (especially anything the user says "
            "they need to do, remember, or get done), marking tasks as done, "
            "deleting tasks, listing pending tasks, and clearing completed tasks. "
            "Always auto-detects priority: words like 'urgent/asap/jaldi' = high, "
            "'later/kal/tomorrow' = low, otherwise = medium."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":   {"type": "STRING",  "description": "add | complete | delete | list | clear"},
                "text":     {"type": "STRING",  "description": "Task description (for add action)"},
                "id":       {"type": "INTEGER", "description": "Task id (for complete/delete action)"},
                "priority": {"type": "STRING",  "description": "high | medium | low (optional for add)"},
                "due":      {"type": "STRING",  "description": "Optional due date string"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "focus_timer",
        "description": (
            "Starts a Pomodoro / focus timer with work and break sessions. "
            "Use when user wants to focus, study, work with timer, or do pomodoro. "
            "Shows a live countdown window and beeps between sessions. "
            "Can also stop or check status of a running timer."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "action":        {"type": "STRING",  "description": "start | stop | status"},
                "work_minutes":  {"type": "INTEGER", "description": "Work session duration in minutes (default: 25)"},
                "break_minutes": {"type": "INTEGER", "description": "Break duration in minutes (default: 5)"},
                "cycles":        {"type": "INTEGER", "description": "Number of work+break cycles (default: 4)"},
            },
            "required": []
        }
    },
    {
        "name": "study_explainer",
        "description": (
            "Visually explains any study topic with a diagram and key points. "
            "ALWAYS call this when the user asks about any academic, school, or study topic: "
            "biology, chemistry, physics, math, history, geography, economics, computer science, etc. "
            "Generate a clear explanation and bullet-point key facts, then display a visual panel."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "topic":       {"type": "STRING", "description": "The exact topic or concept to explain (e.g. 'Photosynthesis', 'Newton\'s Laws', 'Pythagorean Theorem')"},
                "explanation": {"type": "STRING", "description": "A clear 2-3 sentence explanation of the topic in simple words"},
                "points":      {"type": "ARRAY", "items": {"type": "STRING"}, "description": "List of 5-8 key points / bullet facts about the topic"},
            },
            "required": ["topic", "explanation", "points"]
        }
    },

    {
        "name": "save_memory",
        "description": (
            "Save an important personal fact about the user to long-term memory. "
            "CALL THIS PROACTIVELY after every user message — if the user reveals "
            "any personal fact (name, age, city, job, family member, preference, "
            "project, future plan, opinion, habit, etc.), call this tool SILENTLY "
            "before or alongside your reply. Do NOT announce that you are saving. "
            "You may call it multiple times in one turn for multiple facts. "
            "Values must be in English regardless of the conversation language. "
            "Do NOT call for: weather, reminders, searches, one-time commands, "
            "or anything that is not a personal fact about the user."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "category": {
                    "type": "STRING",
                    "description": (
                        "identity — name, age, birthday, city, job, school, language, nationality | "
                        "preferences — favorite food/color/music/film/game/sport, hobbies, habits | "
                        "projects — active projects, study goals, things being built | "
                        "relationships — friends, family, partner, colleagues (e.g. sister_name, friend_rahul) | "
                        "wishes — future plans, things to buy, travel dreams | "
                        "notes — opinions, mood, schedule, recurring topics, anything else"
                    )
                },
                "key":   {"type": "STRING", "description": "Short snake_case key (e.g. name, favorite_food, sister_name, current_goal)"},
                "value": {"type": "STRING", "description": "Concise value in English (e.g. Fatih, pizza, older sister, preparing for NEET)"},
            },
            "required": ["category", "key", "value"]
        }
    },
    {
        "name": "recall_memory",
        "description": (
            "Search long-term memory for facts matching a query. "
            "USE THIS whenever the user asks about something personal they told you before, "
            "their preferences, relationships, projects, or any previously-saved fact. "
            "Examples: 'what's my sister's name?', 'do you remember my favorite food?', "
            "'what are my projects?', 'where do I live?', 'what did I say about…'. "
            "Use empty query or 'all' to list everything on file. "
            "Always include 1-2 keyword(s) from the user's question, NOT the full question. "
            "Quote the returned facts naturally in your reply."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {
                    "type": "STRING",
                    "description": (
                        "Keyword(s) to search for. Use 1-3 keywords, NOT full sentences. "
                        "Examples: 'sister', 'food', 'project', 'city', 'favorite color'. "
                        "Use empty string or 'all' to list every memory on file."
                    )
                },
                "category": {
                    "type": "STRING",
                    "description": (
                        "Optional filter — restrict search to one category: "
                        "identity | preferences | projects | relationships | wishes | notes. "
                        "Omit to search all categories."
                    )
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "Maximum number of matches to return (default 3, max 20). Use 1 for a single best match."
                },
            },
            "required": ["query"]
        }
    },
    {
        "name": "switch_mode",
        "description": (
            "Switches the HUD's operational mode, which reveals (or hides) the "
            "Dynamic Island at the top of the centre screen. Use this when the "
            "user asks to switch, activate, change, or exit a mode — e.g. "
            "'switch to overdrive', 'go focus mode', 'stealth on', 'disable the "
            "island', 'back to normal'. Modes: standard (default, island hidden), "
            "overdrive (combat/intense, red), focus (calm deep work, blue), "
            "stealth (dark/minimal), prism (creative, rainbow), apex (full power, gold)."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "mode": {
                    "type": "STRING",
                    "description": "Mode key: standard | overdrive | focus | stealth | prism | apex"
                }
            },
            "required": ["mode"]
        }
    },
    {
        "name": "pin_card",
        "description": (
            "Pins a card to the Dynamic Island panel. Use proactively for ANY data "
            "the user might want to see visually: web search results, weather, "
            "stock prices, music (now playing), timers, reminders, tasks, notes, "
            "news headlines, quotes, etc. Same type+title REFRESHES the existing "
            "card (e.g. for live weather updates). Pass type-specific fields in 'data'."
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "type": {
                    "type": "STRING",
                    "description": "search | weather | music | timer | stock | note | reminder | task | news | quote | generic"
                },
                "title": {"type": "STRING", "description": "Card title (short, ~30 chars)"},
                "data":  {"type": "OBJECT",  "description": "Type-specific fields. search: {results:[{title,url}]}; weather: {city,temp,condition,humidity}; music: {title,artist,status,progress}; timer: {label,remaining_seconds,status}; stock: {ticker,price,change,change_pct,up}; note: {body}; news: {headline,source}; quote: {body,author}."}
            },
            "required": ["type", "title"]
        }
    },
    {
        "name": "unpin_card",
        "description": "Removes a pinned card from the Dynamic Island panel.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "card_id": {"type": "STRING", "description": "Card id returned from pin_card (or 'all' to clear)"}
            },
            "required": ["card_id"]
        }
    },
    {
        "name": "check_update",
        "description": "Checks if a newer version of Aegis is available on GitHub. Returns version info if an update exists.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "force": {"type": "BOOLEAN", "description": "Force re-check even if recently checked (default: false)"}
            },
            "required": []
        }
    },
    {
        "name": "apply_update",
        "description": "Downloads and installs the latest available update for Aegis. Must only be called after check_update confirms an update exists. The app will restart automatically.",
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "predictive_suggest",
        "description": (
            "Analyzes the current context — time, day, pending tasks, today's calendar events, "
            "and the user's known habits/routines from memory — then returns a structured summary "
            "so you can make smart, proactive suggestions. "
            "Call this at startup (after greeting) and periodically to offer useful suggestions "
            "like 'Sir, aap usually 7pm gym jaate ho, aaj bhi chaloge?' or "
            "'Kal aapki meeting hai, uski tayyari karni hai?'"
        ),
        "parameters": {
            "type": "OBJECT",
            "properties": {},
            "required": []
        }
    },
]

class AegisLive:

    def __init__(self, ui: AegisUI):
        self.ui             = ui
        self.session        = None
        self.audio_in_queue = None
        self.out_queue      = None
        self._loop          = None
        self._is_speaking   = False
        self._speaking_lock = threading.Lock()
        self.ui.on_text_command = self._on_text_command
        try:
            self.ui.on_action(self._on_ui_action)
        except Exception:
            pass
        self._turn_done_event: asyncio.Event | None = None
        self._greeted       = False   # sirf pehli baar greet karne ke liye
        self._latest_update = None    # latest update info from check_update
        # ── Reasoning Trace + Proactive Recall config ──
        self._show_trace      = True
        self._proactive_recall = True
        try:
            self.ui.set_show_trace(self._show_trace)
        except Exception:
            pass

    def _emit_trace(self, kind: str, msg: str) -> None:
        """Push a trace event to the UI (if trace display is enabled)."""
        if not self._show_trace:
            return
        try:
            self.ui.add_trace(kind, msg)
        except Exception:
            pass

    def _maybe_proactive_recall(self, user_text: str) -> None:
        """If user text contains memory keywords, run recall silently
        and surface relevant facts as inline chips."""
        if not self._proactive_recall:
            return
        try:
            import re as _re
            t = (user_text or "").lower()
            if len(t.strip()) < 4:
                return
            # Trigger keywords (Hinglish-aware)
            triggers = (
                r"\b(mera|meri|mere|mujhe|mujh|main|my|i am|i'm|"
                r"remember|yaad|yaadein|fact|facts|prefer|pasand|"
                r"ghar|home|kaam|work|project|delhi|mumbai|"
                r"password|credential|login|birthday|wife|family)\b"
            )
            if not _re.search(triggers, t):
                return
            # Run recall (sync, ~ms)
            from memory.memory_manager import recall_memory
            res = recall_memory(query=user_text[:120], limit=2)
            if not res or "No matching" in res or "no facts" in res.lower():
                return
            # First non-empty line as the fact
            for line in (res or "").splitlines():
                line = line.strip()
                if line and not line.lower().startswith("no ") and len(line) > 8:
                    self.ui.add_recall(user_text[:40], line)
                    break
        except Exception as e:
            print(f"[AEGIS] proactive recall error: {e}")

    # ── Auto-pin helpers (used after relevant tool calls) ─────────────
    def _autopin_weather(self, args: dict, result: str):
        try:
            city = (args.get("city") or "Weather").strip()
            text = (result or "").strip()
            temp = ""
            cond = ""
            hum  = ""
            # crude parse: look for "X°C" and any words after
            import re as _re
            m_t = _re.search(r"(-?\d+)\s*°?\s*C", text)
            if m_t: temp = m_t.group(0)
            # condition: first sentence after temp
            tail = text
            if temp:
                idx = text.find(temp)
                tail = text[idx + len(temp):].strip(" .,-")
            cond = (tail or "Weather")[:50]
            # humidity
            m_h = _re.search(r"(\d{1,3})\s*%", text)
            if m_h: hum = m_h.group(0)
            self.ui.pin_card("weather", f"{city} · {temp or 'Weather'}",
                             {"city": city, "temp": temp or "—",
                              "condition": cond, "humidity": hum})
        except Exception as e:
            print(f"[autopin] weather failed: {e}")

    def _autopin_search(self, args: dict, result: str):
        try:
            query = (args.get("query") or "Search").strip()
            # Parse first 3 result lines: typical format "Title — URL"
            results = []
            for line in (result or "").splitlines():
                line = line.strip(" -•\t")
                if not line or len(line) < 8:
                    continue
                if "http" in line:
                    parts = line.rsplit("http", 1)
                    title = parts[0].strip(" -—") or "Result"
                    url   = "http" + parts[1]
                elif " — " in line:
                    parts = line.split(" — ", 1)
                    title, url = parts[0].strip(), parts[1].strip()
                elif " - " in line:
                    parts = line.split(" - ", 1)
                    title, url = parts[0].strip(), parts[1].strip()
                else:
                    title, url = line, ""
                if not title:
                    continue
                results.append({"title": title[:80], "url": url[:120]})
                if len(results) >= 3:
                    break
            if not results:
                # Just pin a generic note with the result snippet
                self.ui.pin_card("note", f"Search: {query[:30]}", {"body": (result or "")[:200]})
                return
            self.ui.pin_card("search", f"Search: {query[:30]}",
                             {"query": query, "results": results})
        except Exception as e:
            print(f"[autopin] search failed: {e}")

    def _autopin_music(self, args: dict, result: str):
        try:
            action = (args.get("action") or "play").lower()
            if action not in ("play", "search", ""):
                return
            query = (args.get("query") or args.get("url") or "").strip()
            if not query:
                return
            title = query[:40]
            # Heuristic: if " - " in query, split into title/artist
            if " - " in query:
                a, b = query.split(" - ", 1)
                title, artist = a.strip()[:30], b.strip()[:30]
            else:
                title, artist = query[:30], ""
            self.ui.pin_card("music", title,
                             {"title": title, "artist": artist,
                              "status": "playing", "progress": 0.0})
        except Exception as e:
            print(f"[autopin] music failed: {e}")

    def _autopin_timer(self, args: dict, result: str):
        try:
            minutes = float(args.get("minutes") or args.get("duration") or 25)
            label   = (args.get("label") or "Focus").strip()
            self.ui.pin_card("timer", label,
                             {"label": label, "duration_seconds": int(minutes * 60),
                              "remaining_seconds": int(minutes * 60),
                              "status": "running"})
        except Exception as e:
            print(f"[autopin] timer failed: {e}")

    def _autopin_reminder(self, args: dict, result: str):
        try:
            msg = (args.get("message") or "Reminder").strip()
            when = (args.get("date") or "") + " " + (args.get("time") or "")
            self.ui.pin_card("reminder", msg[:30],
                             {"body": msg, "when": when.strip(), "status": "scheduled"})
        except Exception as e:
            print(f"[autopin] reminder failed: {e}")

    def _autopin_note(self, args: dict, result: str):
        try:
            action = (args.get("action") or "").lower()
            if action not in ("add", "create", "save", ""):
                return
            text = (args.get("text") or args.get("content") or args.get("note") or "").strip()
            if not text:
                return
            self.ui.pin_card("note", "Note saved", {"body": text[:160]})
        except Exception as e:
            print(f"[autopin] note failed: {e}")

    def _on_text_command(self, text: str):
        if not self._loop or not self.session:
            return
        # Proactive memory recall — runs before sending to LLM
        try:
            self._maybe_proactive_recall(text)
        except Exception:
            pass
        # Trace the user input
        self._emit_trace("thought", "user → " + (text[:80] if text else ""))
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def _on_ui_action(self, code: str):
        kind, _, val = code.partition(":")
        if kind == "card" and val == "add_files":
            try:
                from actions.file_processor import open_file_dialog
                path = open_file_dialog()
                if path:
                    self._current_file = path
                    self.ui.write_log(f"SYS: File staged - {os.path.basename(path)}")
            except Exception as exc:
                self.ui.write_log(f"ERR: file dialog - {exc}")
            return
        if kind == "card" and val == "memory":
            self.ui.write_log("SYS: Memory subsystem online - working set 38%")
            return
        if kind == "card" and val == "history":
            self.ui.write_log("SYS: Conversation history indexed")
            return
        if kind == "card" and val == "user":
            self.ui.write_log("SYS: User profile active - voice ID confirmed")
            return
        if kind == "tab":
            self.ui.write_log(f"SYS: Module switched - {val.upper()}")
            if val == "notes":
                try:
                    hud = self.ui.hud
                    n = len(hud._notes)
                except Exception:
                    n = 0
                self.ui.write_log(f"SYS: Notes module loaded - {n} note(s) on disk")
            elif val == "tasks":
                try:
                    hud = self.ui.hud
                    pending = sum(1 for t in hud._tasks if not t.get("done"))
                    done    = sum(1 for t in hud._tasks if t.get("done"))
                except Exception:
                    pending = done = 0
                self.ui.write_log(f"SYS: Task module loaded - {pending} pending / {done} done")
            return
        if kind == "minitab" and val == "CALL":
            self.ui.write_log("SYS: Call mode placeholder - mic stream live")
            return
        if kind == "send":
            return
        if kind == "terminate":
            self.ui.write_log("SYS: Terminate acknowledged")
            return
        if kind == "toggle":
            return
        if kind == "hub":
            if val == "reactor":
                self.ui.write_log("SYS: Arc reactor pinged - core nominal")
            else:
                self.ui.write_log("SYS: Visual hub ready - drop an image to analyse")
            return
        if kind == "cmd":
            handler = {
                "web_search":    ("web_search",        "Web search armed - speak your query"),
                "open_browser":  ("browser_control",   "Opening default browser"),
                "play_music":    ("youtube_video",     "Music player ready - name a song"),
                "set_reminder":  ("reminder",          "Reminder armed - what and when?"),
                "send_message":  ("send_message",      "Messaging armed - who and what?"),
                "weather":       ("weather_report",    "Weather check armed - which city?"),
                "flights":       ("flight_finder",     "Flight search armed - from where to where?"),
                "notes":         ("notes_manager",     "Notes mode armed - dictate your note"),
            }.get(val)
            if handler:
                fn_name, msg = handler
                self._current_tool = fn_name
                self.ui.notify_tool(fn_name)
                self.ui.write_log("SYS: " + msg)
            if val == "notes":
                try:
                    self.ui.hud._active_tab = 1
                except Exception:
                    pass
            return

    def set_speaking(self, value: bool):
        with self._speaking_lock:
            self._is_speaking = value
        if value:
            self.ui.set_state("SPEAKING")
        elif not self.ui.muted:
            self.ui.set_state("LISTENING")

    def speak(self, text: str):
        if not self._loop or not self.session:
            return
        asyncio.run_coroutine_threadsafe(
            self.session.send_client_content(
                turns={"parts": [{"text": text}]},
                turn_complete=True
            ),
            self._loop
        )

    def speak_error(self, tool_name: str, error: str):
        short = str(error)[:120]
        self.ui.write_log(f"ERR: {tool_name} — {short}")
        self.speak(f"Sir, {tool_name} encountered an error. {short}")

    def _build_config(self) -> types.LiveConnectConfig:
        from datetime import datetime

        memory     = load_memory()
        mem_str    = format_memory_for_prompt(memory)
        sys_prompt = _load_system_prompt()

        now      = datetime.now()
        time_str = now.strftime("%A, %B %d, %Y — %I:%M %p")
        time_ctx = (
            f"[CURRENT DATE & TIME]\n"
            f"Right now it is: {time_str}\n"
            f"Use this to calculate exact times for reminders.\n\n"
        )

        parts = [time_ctx]
        if mem_str:
            parts.append(mem_str)
        parts.append(sys_prompt)

        return types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            output_audio_transcription={},
            input_audio_transcription={},
            system_instruction="\n".join(parts),
            tools=[{"function_declarations": TOOL_DECLARATIONS}],
            session_resumption=types.SessionResumptionConfig(),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name="Charon"
                    )
                )
            ),
        )

    async def _execute_tool(self, fc) -> types.FunctionResponse:
        name = fc.name
        args = dict(fc.args or {})

        print(f"[AEGIS] 🔧 {name}  {args}")
        self.ui.set_state("THINKING")
        self.ui.notify_tool(name)
        # Trace: tool call starting
        arg_summary = ", ".join(f"{k}={str(v)[:30]}" for k, v in args.items())
        self._emit_trace("tool", f"{name}({arg_summary[:60]})")

        if name == "save_memory":
            category = args.get("category", "notes")
            key      = args.get("key", "")
            value    = args.get("value", "")
            if key and value:
                update_memory({category: {key: {"value": value}}})
                print(f"[Memory] 💾 save_memory: {category}/{key} = {value}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": "ok", "silent": True}
            )

        if name == "recall_memory":
            query    = args.get("query", "")
            category = args.get("category")
            limit    = args.get("limit", 5)
            try:
                result = recall_memory(query=query, category=category, limit=limit)
            except Exception as e:
                result = f"Recall failed: {e}"
                traceback.print_exc()
            print(f"[Memory] 🔍 recall_memory: query='{query}' cat='{category}' → {len(result)} chars")
            self.ui.write_log(f"SYS: Memory recall — '{query[:40]}'")
            # Don't speak — return the result so the LLM can quote it naturally.
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": result, "silent": True}
            )

        if name == "switch_mode":
            mode = (args.get("mode") or "standard").lower().strip()
            ok = self.ui.set_mode(mode)
            if not ok:
                result = f"Unknown mode '{mode}'. Use: standard, overdrive, focus, stealth, prism, apex."
            else:
                from ui import MODES as _MODES
                result = f"Mode switched to {_MODES[mode]['name']}."
            print(f"[HUD] 🎨 switch_mode → {mode}  ok={ok}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": result, "silent": True}
            )

        if name == "pin_card":
            ctype = (args.get("type") or "generic").lower().strip()
            ctitle = (args.get("title") or "").strip() or ctype.upper()
            cdata  = dict(args.get("data") or {})
            try:
                card_id = self.ui.pin_card(ctype, ctitle, cdata)
            except Exception as e:
                result = f"Pin failed: {e}"
                traceback.print_exc()
            else:
                result = f"Pinned {ctype} card '{ctitle}' (id={card_id})."
                print(f"[HUD] 📌 pin_card → {ctype} '{ctitle}'")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": result, "silent": True}
            )

        if name == "unpin_card":
            cid = (args.get("card_id") or "").strip()
            if not cid:
                result = "Missing card_id."
            elif cid.lower() == "all":
                n = self.ui.clear_cards()
                result = f"Cleared {n} card(s)."
            else:
                ok = self.ui.unpin_card(cid)
                result = f"Unpinned {cid}." if ok else f"No such card: {cid}"
            print(f"[HUD] 📍 unpin_card → {cid}")
            if not self.ui.muted:
                self.ui.set_state("LISTENING")
            return types.FunctionResponse(
                id=fc.id, name=name,
                response={"result": result, "silent": True}
            )

        loop   = asyncio.get_event_loop()
        result = "Done."

        try:
            if name == "open_app":
                r = await loop.run_in_executor(None, lambda: open_app(parameters=args, response=None, player=self.ui))
                result = r or f"Opened {args.get('app_name')}."

            elif name == "weather_report":
                r = await loop.run_in_executor(None, lambda: weather_action(parameters=args, player=self.ui))
                result = r or "Weather delivered."
                self._autopin_weather(args, result)

            elif name == "browser_control":
                r = await loop.run_in_executor(None, lambda: browser_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "file_controller":
                r = await loop.run_in_executor(None, lambda: file_controller(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "send_message":
                r = await loop.run_in_executor(None, lambda: send_message(parameters=args, response=None, player=self.ui, session_memory=None))
                result = r or f"Message sent to {args.get('receiver')}."

            elif name == "reminder":
                r = await loop.run_in_executor(None, lambda: reminder(parameters=args, response=None, player=self.ui))
                result = r or "Reminder set."
                self._autopin_reminder(args, result)

            elif name == "youtube_video":
                r = await loop.run_in_executor(None, lambda: youtube_video(parameters=args, response=None, player=self.ui))
                result = r or "Done."
                self._autopin_music(args, result)

            elif name == "screen_process":
                threading.Thread(
                    target=screen_process,
                    kwargs={"parameters": args, "response": None,
                            "player": self.ui, "session_memory": None},
                    daemon=True
                ).start()
                result = "Vision module activated. Stay completely silent — vision module will speak directly."

            elif name == "computer_settings":
                r = await loop.run_in_executor(None, lambda: computer_settings(parameters=args, response=None, player=self.ui))
                result = r or "Done."

            elif name == "desktop_control":
                r = await loop.run_in_executor(None, lambda: desktop_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "code_helper":
                r = await loop.run_in_executor(None, lambda: code_helper(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "dev_agent":
                r = await loop.run_in_executor(None, lambda: dev_agent(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "agent_task":
                from agent.task_queue import get_queue, TaskPriority
                priority_map = {"low": TaskPriority.LOW, "normal": TaskPriority.NORMAL, "high": TaskPriority.HIGH}
                priority = priority_map.get(args.get("priority", "normal").lower(), TaskPriority.NORMAL)
                task_id  = get_queue().submit(goal=args.get("goal", ""), priority=priority, speak=self.speak)
                result   = f"Task started (ID: {task_id})."

            elif name == "agent_delegate":
                from agent.manager import get_manager
                goal = args.get("goal", "")
                self.ui.write_log(f"SYS: Deploying multi-agent pipeline for: {goal[:60]}")
                mgr = get_manager()
                def progress(name, status):
                    self.ui._agent_status = mgr.get_pipeline_status()
                result = await loop.run_in_executor(
                    None,
                    lambda: mgr.run_pipeline(goal=goal, speak=self.speak, progress_cb=progress)
                )

            elif name == "web_search":
                r = await loop.run_in_executor(None, lambda: web_search_action(parameters=args, player=self.ui))
                result = r or "Done."
                self._autopin_search(args, result)
            elif name == "file_processor":
                if not args.get("file_path") and self.ui.current_file:
                    args["file_path"] = self.ui.current_file
                r = await loop.run_in_executor(
                    None,
                    lambda: file_processor(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Done."

            elif name == "computer_control":
                r = await loop.run_in_executor(None, lambda: computer_control(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "game_updater":
                r = await loop.run_in_executor(None, lambda: game_updater(parameters=args, player=self.ui, speak=self.speak))
                result = r or "Done."

            elif name == "flight_finder":
                r = await loop.run_in_executor(None, lambda: flight_finder(parameters=args, player=self.ui))
                result = r or "Done."

            elif name == "shutdown_aegis":
                self.ui.write_log("SYS: Shutdown requested.")
                self.speak("Goodbye, sir.")
                def _shutdown():
                    import time, os
                    time.sleep(1)
                    os._exit(0)
                threading.Thread(target=_shutdown, daemon=True).start()

            elif name == "calendar_manager":
                r = await loop.run_in_executor(None, lambda: calendar_manager(parameters=args, player=self.ui))
                result = r or "Calendar updated."

            elif name == "notes_manager":
                r = await loop.run_in_executor(None, lambda: notes_manager(parameters=args, player=self.ui))
                result = r or "Note saved."
                try:
                    self.ui.hud._notes = self.ui.hud._load_notes()
                    self.ui.hud._active_tab = 1
                except Exception:
                    pass
                self._autopin_note(args, result)

            elif name == "task_manager":
                r = await loop.run_in_executor(None, lambda: task_manager(parameters=args, player=self.ui))
                result = r or "Task updated."
                try:
                    self.ui.hud._tasks = self.ui.hud._load_tasks()
                    self.ui.hud._active_tab = 2
                except Exception:
                    pass

            elif name == "focus_timer":
                r = await loop.run_in_executor(
                    None,
                    lambda: focus_timer(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Timer started."
                self._autopin_timer(args, result)

            elif name == "study_explainer":
                r = await loop.run_in_executor(
                    None,
                    lambda: study_explainer(parameters=args, player=self.ui, speak=self.speak)
                )
                result = r or "Study panel displayed."

            elif name == "check_update":
                force = args.get("force", False)
                try:
                    info = updater.check_for_updates(force=force)
                    if info:
                        result = f"Update available: v{info['version']}. Release: {info['release_url']}"
                        if info.get("body"):
                            result += f"\nNotes: {info['body'][:300]}"
                        self._latest_update = info
                    else:
                        result = "No updates available. You are on the latest version."
                        self._latest_update = None
                except Exception as e:
                    result = f"Update check failed: {e}"

            elif name == "apply_update":
                info = getattr(self, "_latest_update", None)
                if not info:
                    result = "No pending update. Run check_update first to find an available update."
                elif not info.get("download_url"):
                    result = "Update found but no downloadable asset available. Please download manually from GitHub."
                else:
                    try:
                        result = "Downloading update..."
                        self.ui.write_log("SYS: Downloading update...")
                        import threading as _t
                        def _do_update():
                            try:
                                update_path = updater.download_update(info)
                                self.ui.write_log("SYS: Update downloaded. Installing...")
                                updater.apply_update(update_path)
                            except Exception as e:
                                self.ui.write_log(f"SYS: Update failed: {e}")
                        _t.Thread(target=_do_update, daemon=True).start()
                    except Exception as e:
                        result = f"Update failed: {e}"

            elif name == "predictive_suggest":
                r = await loop.run_in_executor(
                    None,
                    lambda: predictive_suggest(parameters=args, player=self.ui)
                )
                result = r or "No suggestions available."

            else:
                result = f"Unknown tool: {name}"

        except Exception as e:
            result = f"Tool '{name}' failed: {e}"
            traceback.print_exc()
            self.speak_error(name, e)

        if not self.ui.muted:
            self.ui.set_state("LISTENING")

        print(f"[AEGIS] 📤 {name} → {str(result)[:80]}")
        # Trace: tool call result
        result_kind = "result" if "fail" not in str(result).lower() and "error" not in str(result).lower() else "error"
        self._emit_trace(result_kind, f"{name} → {str(result)[:60]}")
        self.ui.notify_tool("")
        return types.FunctionResponse(
            id=fc.id, name=name,
            response={"result": result}
        )

    async def _send_realtime(self):
        while True:
            msg = await self.out_queue.get()
            await self.session.send_realtime_input(media=msg)

    async def _listen_audio(self):
        print("[AEGIS] 🎤 Mic started")
        loop = asyncio.get_event_loop()

        def callback(indata, frames, time_info, status):
            with self._speaking_lock:
                aegis_speaking = self._is_speaking
            if not aegis_speaking and not self.ui.muted:
                data = indata.tobytes()
                loop.call_soon_threadsafe(
                    self.out_queue.put_nowait,
                    {"data": data, "mime_type": "audio/pcm"}
                )

        try:
            with sd.InputStream(
                samplerate=SEND_SAMPLE_RATE,
                channels=CHANNELS,
                dtype="int16",
                blocksize=CHUNK_SIZE,
                callback=callback,
            ):
                print("[AEGIS] 🎤 Mic stream open")
                while True:
                    await asyncio.sleep(0.1)
        except Exception as e:
            print(f"[AEGIS] ❌ Mic: {e}")
            raise

    async def _receive_audio(self):
        print("[AEGIS] 👂 Recv started")
        out_buf, in_buf = [], []

        try:
            while True:
                async for response in self.session.receive():

                    if response.data:
                        if self._turn_done_event and self._turn_done_event.is_set():
                            self._turn_done_event.clear()
                        self.audio_in_queue.put_nowait(response.data)

                    if response.server_content:
                        sc = response.server_content

                        if sc.output_transcription and sc.output_transcription.text:
                            txt = _clean_transcript(sc.output_transcription.text)
                            if txt:
                                out_buf.append(txt)

                        if sc.input_transcription and sc.input_transcription.text:
                            txt = _clean_transcript(sc.input_transcription.text)
                            if txt:
                                in_buf.append(txt)

                        if sc.turn_complete:
                            if self._turn_done_event:
                                self._turn_done_event.set()

                            full_in = " ".join(in_buf).strip()
                            if full_in:
                                self.ui.write_log(f"You: {full_in}")
                            in_buf = []

                            full_out = " ".join(out_buf).strip()
                            if full_out:
                                self.ui.write_log(f"Aegis: {full_out}")
                            out_buf = []

                    if response.tool_call:
                        fn_responses = []
                        for fc in response.tool_call.function_calls:
                            print(f"[AEGIS] 📞 {fc.name}")
                            fr = await self._execute_tool(fc)
                            fn_responses.append(fr)
                        await self.session.send_tool_response(
                            function_responses=fn_responses
                        )
        except Exception as e:
            print(f"[AEGIS] ❌ Recv: {e}")
            traceback.print_exc()
            raise

    async def _play_audio(self):
        print("[AEGIS] 🔊 Play started")

        stream = sd.RawOutputStream(
            samplerate=RECEIVE_SAMPLE_RATE,
            channels=CHANNELS,
            dtype="int16",
            blocksize=CHUNK_SIZE,
        )
        stream.start()

        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(),
                        timeout=0.1
                    )
                except asyncio.TimeoutError:
                    if (
                        self._turn_done_event
                        and self._turn_done_event.is_set()
                        and self.audio_in_queue.empty()
                    ):
                        self.set_speaking(False)
                        self._turn_done_event.clear()
                    self.ui.set_audio_level(0.0)
                    continue
                self.set_speaking(True)
                try:
                    import struct
                    samples = struct.unpack("<" + "h" * (len(chunk) // 2), chunk)
                    if samples:
                        peak = max(1, max(abs(s) for s in samples))
                        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                        level = min(1.0, (rms / peak) * 2.5)
                    else:
                        level = 0.0
                    self.ui.set_audio_level(level)
                except Exception:
                    pass
                await asyncio.to_thread(stream.write, chunk)
        except Exception as e:
            print(f"[AEGIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            self.ui.set_audio_level(0.0)
            stream.stop()
            stream.close()

    def _should_show_news_today(self) -> bool:
        """Check karo ki aaj news pehle se dikhayi hai ya nahi."""
        from datetime import date
        news_file = BASE_DIR / "config" / "last_news.json"
        try:
            if news_file.exists():
                with open(news_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                last_date = data.get("last_news_date", "")
                if last_date == str(date.today()):
                    return False  # aaj pehle se news bol chuka hai
        except Exception:
            pass
        return True

    def _mark_news_shown(self):
        """Aaj ki date save karo taaki dobara news na bole."""
        from datetime import date
        news_file = BASE_DIR / "config" / "last_news.json"
        try:
            news_file.parent.mkdir(parents=True, exist_ok=True)
            with open(news_file, "w", encoding="utf-8") as f:
                json.dump({"last_news_date": str(date.today())}, f)
        except Exception as e:
            print(f"[AEGIS] \u26a0\ufe0f Could not save news date: {e}")

    async def _send_startup_greeting(self):
        """Pehli baar connect hone par greet karo, pending tasks yaad dilao, aur news bolo."""
        if self._greeted:
            return
        self._greeted = True

        await asyncio.sleep(1.5)

        show_news = self._should_show_news_today()

        if show_news:
            startup_msg = (
                "STARTUP SEQUENCE: Now follow your PERSONAL ASSISTANT greeting protocol. "
                "First greet me based on the current time, then check my pending tasks "
                "using task_manager(list) and tell me what's still pending from before. "
                "Give me a smart suggestion for today. "
                "Then search the web and tell me the top 3 latest news headlines "
                "from India and the world right now. Keep it very brief."
            )
        else:
            startup_msg = (
                "STARTUP SEQUENCE: Now follow your PERSONAL ASSISTANT greeting protocol. "
                "First greet me based on the current time, then check my pending tasks "
                "using task_manager(list) and tell me what's still pending from before. "
                "Give me a smart suggestion for today."
            )

        await self.session.send_client_content(
            turns={"parts": [{"text": startup_msg}]},
            turn_complete=True
        )

        if show_news:
            self._mark_news_shown()

    async def run(self):
        client = genai.Client(
            api_key=_get_api_key(),
            http_options={"api_version": "v1beta"}
        )

        while True:
            try:
                print("[AEGIS] Connecting...")
                self.ui.set_state("THINKING")
                config = self._build_config()

                async with (
                    client.aio.live.connect(model=LIVE_MODEL, config=config) as session,
                    asyncio.TaskGroup() as tg,
                ):
                    self.session        = session
                    self._loop          = asyncio.get_event_loop()
                    self.audio_in_queue = asyncio.Queue()
                    self.out_queue      = asyncio.Queue(maxsize=10)
                    self._turn_done_event = asyncio.Event()

                    print("[AEGIS] Connected.")
                    self.ui.set_state("LISTENING")
                    self.ui.write_log("SYS: AEGIS online.")

                    tg.create_task(self._send_realtime())
                    tg.create_task(self._listen_audio())
                    tg.create_task(self._receive_audio())
                    tg.create_task(self._play_audio())
                    tg.create_task(self._send_startup_greeting())

            except Exception as e:
                print(f"[AEGIS] Error: {e}")
                traceback.print_exc()
            self.set_speaking(False)
            self.ui.set_state("THINKING")
            print("[AEGIS] Reconnecting in 3s...")
            await asyncio.sleep(3)

def _check_update_background(ui):
    try:
        info = updater.check_for_updates()
        if info:
            ui.write_log(f"SYS: Update v{info['version']} available! Release: {info['release_url']}")
            try:
                pin_data = {"version": info["version"], "release_url": info["release_url"]}
                ui.pin_card("update", f"Update Available v{info['version']}", pin_data)
            except Exception:
                pass
    except Exception as e:
        print(f"[Updater] startup check error: {e}")

def main():
    ui = AegisUI("face.png")

    def runner():
        ui.wait_for_api_key()
        threading.Thread(target=_check_update_background, args=(ui,), daemon=True).start()
        aegis = AegisLive(ui)
        try:
            asyncio.run(aegis.run())
        except KeyboardInterrupt:
            print("\nShutting down...")

    threading.Thread(target=runner, daemon=True).start()
    ui.root.mainloop()

if __name__ == "__main__":
    main()




