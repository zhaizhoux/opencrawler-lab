// OpenCrawlerLauncher —— 极小的 Win32 GUI 启动器（零控制台、零依赖）。
//
// 优先级：
//   1. 打包版 OpenCrawlerLab.exe（PyInstaller 单文件程序，通常在 dist/）
//   2. pythonw.exe / python.exe + desktop/launcher.py（源码运行）
//
// 启动器放在项目根目录、desktop/ 或 dist/ 下都能自动定位：
//   <root>/OpenCrawlerLab.exe、<root>/dist/OpenCrawlerLab.exe、
//   <root>/desktop/launcher.py
//
// 额外参数原样转发，例如：
//   OpenCrawlerLauncher.exe --no-browser --port 9000
//
// 编译（MinGW-w64）：
//   g++ -O2 -s -mwindows win_launcher.cpp -o OpenCrawlerLauncher.exe
//
// 启动器本身只负责「打开桌面窗口」，不含任何爬虫逻辑，
// 因此 Python 侧升级后无需重新编译 C++ 即可生效。
#include <windows.h>

#include <string>
#include <vector>

static std::wstring DirOfModule() {
    std::vector<wchar_t> buf(MAX_PATH * 4, L'\0');
    GetModuleFileNameW(nullptr, buf.data(), static_cast<DWORD>(buf.size()));
    std::wstring path(buf.data());
    const size_t pos = path.find_last_of(L"\\/");
    return pos == std::wstring::npos ? std::wstring(L".") : path.substr(0, pos);
}

static std::wstring Join(const std::wstring& dir, const wchar_t* tail) {
    return dir + L"\\" + tail;
}

static bool Exists(const std::wstring& path) {
    return GetFileAttributesW(path.c_str()) != INVALID_FILE_ATTRIBUTES;
}

// 把启动器自身的额外参数原样转给主程序。
// GetCommandLineW() 的第一个 token 是可执行文件，需按引号规则跳过。
static std::wstring ExtraArgs() {
    std::wstring cl = GetCommandLineW();
    std::size_t i = 0;
    if (!cl.empty() && cl[0] == L'"') {
        std::size_t end = cl.find(L'"', 1);
        i = end == std::wstring::npos ? cl.size() : end + 1;
    } else {
        i = cl.find_first_of(L" \t");
        if (i == std::wstring::npos) i = cl.size();
    }
    while (i < cl.size() && (cl[i] == L' ' || cl[i] == L'\t')) ++i;
    return cl.substr(i);
}

static bool Start(const std::wstring& exe, const std::wstring& args, const std::wstring& dir) {
    std::vector<wchar_t> cmd(args.begin(), args.end());
    cmd.push_back(L'\0');
    STARTUPINFOW si{};
    si.cb = sizeof(si);
    PROCESS_INFORMATION pi{};
    const BOOL ok = CreateProcessW(
        exe.empty() ? nullptr : exe.c_str(), cmd.data(), nullptr, nullptr, FALSE,
        CREATE_NO_WINDOW, nullptr, dir.c_str(), &si, &pi);
    if (!ok) return false;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return true;
}

static void Fail(const wchar_t* msg) {
    MessageBoxW(nullptr, msg, L"OpenCrawlerLab 启动失败", MB_ICONERROR | MB_OK);
}

int WINAPI WinMain(HINSTANCE, HINSTANCE, LPSTR, int) {
    const std::wstring here = DirOfModule();
    // 启动器在项目根目录时 root == here；在 desktop/ 或 dist/ 时 root 是上一级。
    const bool looksNested = Exists(Join(here, L"desktop\\launcher.py"))
        || Exists(Join(here, L"dist\\OpenCrawlerLab.exe"))
        || Exists(Join(here, L"launcher.py"))
        || Exists(Join(here, L"..\\desktop\\launcher.py"));
    const std::wstring root = looksNested ? here + L"\\.." : here;
    const std::wstring extra = ExtraArgs();
    const std::wstring suffix = extra.empty() ? L"" : L" " + extra;

    // 1) 打包版：兼容「放在 dist/ 同目录」「放在项目根」「放在 desktop/」三种布局
    const std::wstring packed[] = {
        Join(here, L"OpenCrawlerLab.exe"),
        Join(here, L"dist\\OpenCrawlerLab.exe"),
        Join(root, L"dist\\OpenCrawlerLab.exe"),
        Join(root, L"OpenCrawlerLab.exe"),
    };
    for (const auto& exe : packed) {
        if (!Exists(exe)) continue;
        const std::wstring dir = exe.substr(0, exe.find_last_of(L"\\/"));
        if (Start(exe, L"\"" + exe + L"\"" + suffix, dir)) return 0;
    }

    // 2) 源码运行：找 launcher.py，再找解释器
    const std::wstring scripts[] = {
        Join(root, L"desktop\\launcher.py"),
        Join(here, L"desktop\\launcher.py"),
        Join(here, L"launcher.py"),
    };
    std::wstring script;
    for (const auto& s : scripts) {
        if (Exists(s)) { script = s; break; }
    }
    if (script.empty()) {
        Fail(L"未找到 OpenCrawlerLab.exe，也未找到 desktop\\launcher.py。\n"
             L"已尝试启动器所在目录、其上一级目录与 dist\\ 子目录。\n"
             L"请保留原有目录结构，或先运行 desktop\\build_exe.py。");
        return 1;
    }
    const wchar_t* candidates[] = {
        L"pythonw.exe", L"python.exe",
        L"C:\\Windows\\pyw.exe", L"C:\\Windows\\py.exe",
    };
    for (const wchar_t* name : candidates) {
        std::wstring args = std::wstring(L"\"") + name + L"\" \"" + script + L"\"" + suffix;
        if (Start(name, args, root)) return 0;
    }
    Fail(L"找到 desktop\\launcher.py，但找不到 Python 解释器。\n"
         L"请安装 Python 3.11+ 并加入 PATH，或先运行 desktop\\build_exe.py 生成独立 exe。");
    return 1;
}
