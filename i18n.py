"""Two languages for one window.

Every fixed string in the interface is written in English where it is used and
looked up here when the window is running in Chinese. The English stays in the
code it belongs to -- a button still reads ``RESET`` at the line that builds
it -- and the second language is one table in one file rather than a second
copy of the interface.

No data on disk is translated. stats.json, settings.json and the .json half of
every archive keep their English keys and their English layout names whichever
language the window is showing, and switching languages never rewrites a file.

The .png half of an archive is the exception, and deliberately: it is not data
but a photograph of the console as it stood, so it is written in the language
that was on the console at the time. A run filed in Chinese hangs in the
gallery in Chinese; the counts behind it read the same in either language.

The Chinese is held to the same length as the English it stands in for. These
are labels on a console, not sentences: a label that wraps is a label that has
stopped working.
"""

from __future__ import annotations


ENGLISH = "en"
CHINESE = "zh"
LANGUAGES = (ENGLISH, CHINESE)

# What each language calls itself. The switch in the header wears the name of
# the language it would take you to, never of the one you are already reading:
# one button, and no second word beside it explaining the first.
LANGUAGE_BUTTON = {ENGLISH: "EN", CHINESE: "中文"}

_language = ENGLISH


CHINESE_TEXT: dict[str, str] = {
    # -- header ----------------------------------------------------------
    "●  LIVE": "●  监听中",
    "○  NO GAMEPAD": "○  未连接手柄",
    "●  KEYBOARD ERROR": "●  键盘异常",
    "●  GAMEPAD ERROR": "●  手柄异常",
    "Every key on this machine is being counted.": "本机的每一次敲击都在统计。",
    "No controller is connected. Plug one in and KeyPulse finds it on its own.":
        "未连接手柄。插上手柄，KeyPulse 会自己找到它。",
    "Reading the controller in slot {slot}.": "正在读取 {slot} 号手柄。",
    "RESET": "重置",
    "Archive the counts of the device on screen, then start from zero":
        "把当前设备的计数归档，然后从零开始",
    "MONITOR": "实况",
    "Watch the device you are using": "看着正在用的设备",
    "GALLERY": "画廊",
    "Every run archived so far, hung on a wall": "至今归档的每一段记录，挂成一墙",
    "Switch the interface to Chinese": "把界面切换成中文",
    "Switch the interface to English": "把界面切换成英文",

    # -- summary cards ---------------------------------------------------
    "TODAY": "今日",
    "TOTAL": "总计",
    "TOP KEY": "最常用键",
    "TOP BUTTON": "最常用按键",

    # -- toolbar ---------------------------------------------------------
    "SHOW": "显示",
    "KEYBOARD": "键盘",
    "GAMEPAD": "手柄",
    "Show the keyboard and its key counts": "显示键盘和它的按键计数",
    "Show the controller and its button counts": "显示手柄和它的按键计数",
    "LAYOUT": "配列",
    "MODEL": "型号",
    "LIGHT": "灯光",
    "Turn the lighting of the device on screen on or off": "开关当前设备的灯光",
    "STARTUP": "开机自启",
    "Start counting in the background when Windows starts":
        "登录 Windows 后自动在后台开始统计",
    "Scroll to zoom the device, drag to slide it": "滚轮缩放，拖动平移",

    # -- keyboard layouts and pad models ---------------------------------
    # All four boards are named the one way -- what the shape is called, and
    # how many keys that comes to -- rather than two of them by size and two
    # by percentage, which is what the English names happen to do.
    "Full Size": "全尺寸（104 键）",
    "TKL 87": "TKL（87 键）",
    "60%": "60%（61 键）",
    "75%": "75%（83 键）",
    # All four pads are named the way the box names them, so all four stay in
    # English: Xbox, PlayStation, Switch Pro, Wired. "Wired" had a Chinese
    # reading here once and it read as a category rather than as a model.

    # -- tray ------------------------------------------------------------
    "Open": "打开",
    "Exit": "退出",
    "Still running": "仍在运行",
    "KeyPulse is in the system tray.": "KeyPulse 缩在系统托盘里。",

    # -- reset -----------------------------------------------------------
    "Reset": "重置",
    "No keystrokes to reset.": "没有可重置的敲击记录。",
    "No button presses to reset.": "没有可重置的按键记录。",
    "The board is already at zero, so there is no run worth archiving.":
        "键盘的计数已经是零，没有值得归档的记录。",
    "The pad is already at zero, so there is no run worth archiving.":
        "手柄的计数已经是零，没有值得归档的记录。",
    "OK": "好",
    "Reset counts": "计数重置",
    "Reset every keyboard count to zero?": "把键盘的每一项计数都重置为零？",
    "Reset every gamepad count to zero?": "把手柄的每一项计数都重置为零？",
    "The current run — {total} keystrokes across {distinct} keys — is hung in the "
    "gallery first, as a picture of the board plus the counts behind it. The other "
    "device keeps its own counts.":
        "当前这段记录 —— {distinct} 个按键上的 {total} 次敲击 —— 会先挂进画廊：一张键盘的"
        "图片，加上它背后的计数。另一台设备的计数不受影响。",
    "The current run — {total} button presses across {distinct} buttons — is hung in the "
    "gallery first, as a picture of the pad plus the counts behind it. The other "
    "device keeps its own counts.":
        "当前这段记录 —— {distinct} 个按键上的 {total} 次按下 —— 会先挂进画廊：一张手柄的"
        "图片，加上它背后的计数。另一台设备的计数不受影响。",
    "Archive and reset": "归档并重置",
    "Cancel": "取消",
    "Reset failed": "重置失败",
    "The snapshot could not be written, so the counts were kept.":
        "快照没能写进磁盘，所以计数保留了下来。",
    "Counts reset": "计数已重置",
    "The board is back to zero.": "键盘已经归零。",
    "The pad is back to zero.": "手柄已经归零。",
    "The run it just finished is hanging in the gallery, kept on disk as {file} with "
    "the same counts as .json beside it.":
        "刚结束的这段记录已挂在画廊里，图片存为 {file}，装着同一份计数的 .json 就在它旁边。",
    "Open gallery": "打开画廊",
    "Done": "完成",

    # -- errors ----------------------------------------------------------
    "Startup Error": "启动错误",
    "The startup setting could not be changed.": "没能改掉开机自启的设置。",
    "Windows only.": "仅支持 Windows。",
    "KeyPulse cannot use its folder {folder}.": "KeyPulse 用不了它的文件夹 {folder}。",
    "The picture {file} could not be written.": "图片 {file} 没能写入磁盘。",
    "Already Running": "已经在运行",
    "Open KeyPulse from the system tray.": "请从系统托盘打开 KeyPulse。",
    "Keyboard monitoring error": "键盘监听出错",
    "Controller monitoring error": "手柄监听出错",
    "Keyboard monitoring failed (Windows error {code}).": "键盘监听失败（Windows 错误 {code}）。",
    "No XInput runtime was found, so controllers cannot be read.":
        "没找到 XInput 运行库，读不到手柄。",

    # -- gallery: the wall -----------------------------------------------
    "WALL": "展墙",
    "Runs archived from the keyboard": "从键盘归档的记录",
    "Runs archived from the controller": "从手柄归档的记录",
    "{pieces} piece": "{pieces} 幅",
    "{pieces} pieces": "{pieces} 幅",
    "FOLDER": "文件夹",
    "Open the folder this wall is filed in": "打开这面墙对应的存档文件夹",
    "Nothing is hanging here yet": "这里还什么都没挂",
    "The keyboard wall is empty": "键盘这面墙还空着",
    "The pad wall is empty": "手柄这面墙还空着",
    "RESET files the current run as a picture. It is hung here.":
        "「重置」会把当前记录存成一张图片，挂到这里。",
    "Click for the counts behind this picture": "点一下，看这张图片背后的计数",
    "loading...": "载入中…",

    # -- gallery: one exhibit --------------------------------------------
    "←  WALL": "←  展墙",
    "Back to the wall": "回到展墙",
    "COPY JSON": "复制 JSON",
    "Copy the whole file to the clipboard": "把整个文件复制到剪贴板",
    "SHOW FILE": "定位文件",
    "Show this file in Explorer": "在资源管理器里定位这个文件",
    "REMOVE": "删除",
    "Delete this picture and its counts from disk": "从磁盘删掉这张图片和它的计数",
    "BUSIEST": "最频繁",
    "EXHIBIT LABEL": "展签",
    "Counted from": "统计始于",
    "Counted until": "统计止于",
    "Span": "跨度",
    "Dates covered": "覆盖日期",
    "Total": "总计",
    "Distinct": "不同按键",
    "Device": "设备",
    "File": "文件",
    "No. {number}   ·   {title}": "第 {number} 号   ·   {title}",
    "   (first day)": "   （首日）",
    "Keyboard": "键盘",
    "Gamepad": "手柄",
    "picture missing": "图片缺失",
    "the picture of this run is missing": "这段记录的图片不见了",
    "Remove exhibit": "撤下展品",
    "Take No. {number} off the wall?": "把第 {number} 号从墙上取下来？",
    "{file} and its picture are deleted from disk, from every folder KeyPulse keeps "
    "archives in. This cannot be undone.":
        "{file} 和它的图片会从 KeyPulse 存放归档的每个文件夹里删除，且无法撤销。",
    "Delete": "删除",
    "Remove failed": "删除失败",
    "Part of this exhibit could not be deleted.": "这件展品有一部分没能删掉。",

    # -- the things being counted, as they are read out ------------------
    "{total} keystrokes": "{total} 次敲击",
    "{total} presses": "{total} 次按下",
    # Read out under a caption that already names them, so the noun stays
    # there rather than being said twice across one row.
    "{count} keys": "{count} 个",
    "{count} buttons": "{count} 个",

    # -- spans -----------------------------------------------------------
    "under a minute": "不到一分钟",
    "{days} d": "{days} 天",
    "{hours} h": "{hours} 小时",
    "{minutes} m": "{minutes} 分钟",

    # -- the archived picture --------------------------------------------
    "ARCHIVED  {moment}": "归档于  {moment}",
    "{layout}  ·  {count} keys used": "{layout}  ·  用过 {count} 个按键",
    "{layout}  ·  {count} buttons used": "{layout}  ·  用过 {count} 个按键",
}


# A few English strings mean one thing in one corner of the window and another
# somewhere else. Those are keyed by where they are said as well as by what
# they say; everything else shares the one table.
CHINESE_IN_CONTEXT: dict[tuple[str, str], str] = {
    ("startup", "Startup Error"): "开机自启失败",
}


def language() -> str:
    """Which language the window is speaking."""
    return _language


def other_language() -> str:
    """The one it is not -- what the switch in the header would put it into."""
    return ENGLISH if _language == CHINESE else CHINESE


def set_language(code: str) -> str:
    """Speak the given language from here on. Anything unknown means English."""
    global _language
    _language = CHINESE if code == CHINESE else ENGLISH
    return _language


def tr(text: str, context: str = "") -> str:
    """The given English, in whichever language the window is speaking.

    English is the source, so it comes back untouched; anything the Chinese
    table has no entry for falls back to it rather than to a blank.
    """
    if _language != CHINESE:
        return text
    if context:
        wording = CHINESE_IN_CONTEXT.get((context, text))
        if wording is not None:
            return wording
    return CHINESE_TEXT.get(text, text)


class Wording:
    """The fixed strings on screen, each remembered by its English source.

    A label set once while the window was being built has no idea what it says
    by the time the language changes, and asking every one of them to keep its
    own copy would spread the same three lines over the whole file. So each
    string is registered here as it is applied, and the whole set is applied
    again when the switch is thrown.

    Anything that changes on its own -- a count, the status light, the name of
    the layout in the combo -- is not registered: the refresh that already
    writes it is what puts it into the new language.
    """

    def __init__(self) -> None:
        self._labels: list[tuple[object, str]] = []
        self._tips: list[tuple[object, str]] = []

    def label(self, widget, source: str, tip: str = ""):
        """Give a widget its text, and remember where that text came from."""
        widget.setText(tr(source))
        self._labels.append((widget, source))
        if tip:
            self.tip(widget, tip)
        return widget

    def tip(self, widget, source: str):
        """The same, for the tooltip a widget carries."""
        widget.setToolTip(tr(source))
        self._tips.append((widget, source))
        return widget

    def apply(self) -> None:
        """Say all of it again, in the language now in force."""
        for widget, source in self._labels:
            widget.setText(tr(source))
        for widget, source in self._tips:
            widget.setToolTip(tr(source))
