// Direct3D9 transparent overlay (optimized)
// Binary UDP protocol on 127.0.0.1:7777
// GDI text on window DC (no LOCKABLE_BACKBUFFER needed)
// Dirty-flag rendering
//
// Build:
// 1. Visual Studio -> C++ Win32 project (x86)
// 2. Linker -> Additional Dependencies: d3d9.lib ws2_32.lib

#define WIN32_LEAN_AND_MEAN
#define _WINSOCK_DEPRECATED_NO_WARNINGS
#include <winsock2.h>
#pragma comment(lib, "ws2_32.lib")

#include <windows.h>
#include <d3d9.h>
#include <vector>
#include <string>
#include <cstdint>
#include <cmath>

#pragma comment(lib, "d3d9.lib")
#pragma comment(linker, "/SUBSYSTEM:WINDOWS")

LPDIRECT3D9       g_pD3D    = nullptr;
LPDIRECT3DDEVICE9 g_pDevice = nullptr;
HWND              g_hWnd    = nullptr;
bool              g_Running = true;
int               g_VirtualX = 0;
int               g_VirtualY = 0;
HFONT             g_hFont     = nullptr;
HFONT             g_hIconFont = nullptr;

SOCKET g_sock = INVALID_SOCKET;

// --- Binary protocol command tags (must match Python side) ---
static const uint8_t CMD_LINE     = 0x01;
static const uint8_t CMD_RECT     = 0x02;
static const uint8_t CMD_TEXT     = 0x03;
static const uint8_t CMD_GAME_WIN = 0x04;

#pragma pack(push, 1)
struct BinLine {
    uint8_t  type;
    float    x1, y1, x2, y2;
    uint32_t color;
    float    thickness;
};

struct BinRect {
    uint8_t  type;
    float    x1, y1, x2, y2;
    uint32_t color;
};

struct BinTextHdr {
    uint8_t  type;
    float    x, y;
    uint8_t  size;
    uint32_t color;
    uint8_t  icon;
    uint8_t  textLen;
};

struct BinGameWin {
    uint8_t type;
    int32_t x, y, w, h;
};
#pragma pack(pop)

struct LineCmd {
    float x1, y1, x2, y2;
    D3DCOLOR color;
    float thickness;
};

struct RectCmd {
    float x1, y1, x2, y2;
    D3DCOLOR color;
};

struct TextCmd {
    float x, y;
    int   size;
    D3DCOLOR color;
    std::string text;
    bool icon;
};

std::vector<LineCmd> g_lines;
std::vector<RectCmd> g_rects;
std::vector<TextCmd> g_texts;
CRITICAL_SECTION g_cs;

int  g_GameX = 0, g_GameY = 0, g_GameW = 0, g_GameH = 0;
bool g_GameWindowDirty = false;
bool g_DataDirty = false;
CRITICAL_SECTION g_csWin;

struct TLVERTEX {
    float x, y, z, rhw;
    D3DCOLOR color;
};
#define D3DFVF_TLVERTEX (D3DFVF_XYZRHW | D3DFVF_DIFFUSE)

LRESULT CALLBACK WndProc(HWND hWnd, UINT msg, WPARAM wParam, LPARAM lParam) {
    switch (msg) {
    case WM_DESTROY:
        g_Running = false;
        PostQuitMessage(0);
        return 0;
    default:
        return DefWindowProc(hWnd, msg, wParam, lParam);
    }
}

bool InitD3D(HWND hWnd) {
    g_pD3D = Direct3DCreate9(D3D_SDK_VERSION);
    if (!g_pD3D) return false;

    D3DPRESENT_PARAMETERS d3dpp{};
    d3dpp.Windowed            = TRUE;
    d3dpp.SwapEffect          = D3DSWAPEFFECT_DISCARD;
    d3dpp.hDeviceWindow       = hWnd;
    d3dpp.BackBufferFormat    = D3DFMT_A8R8G8B8;
    d3dpp.EnableAutoDepthStencil = FALSE;

    HRESULT hr = g_pD3D->CreateDevice(
        D3DADAPTER_DEFAULT, D3DDEVTYPE_HAL, hWnd,
        D3DCREATE_SOFTWARE_VERTEXPROCESSING, &d3dpp, &g_pDevice);
    if (FAILED(hr)) return false;

    g_pDevice->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
    g_pDevice->SetRenderState(D3DRS_SRCBLEND,  D3DBLEND_SRCALPHA);
    g_pDevice->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
    g_pDevice->SetFVF(D3DFVF_TLVERTEX);

    g_hFont = CreateFontA(
        16, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        DEFAULT_QUALITY, DEFAULT_PITCH | FF_DONTCARE, "Arial");

    AddFontResourceExA("weapon_font.ttf", FR_PRIVATE, 0);
    g_hIconFont = CreateFontA(
        24, 0, 0, 0, FW_NORMAL, FALSE, FALSE, FALSE,
        DEFAULT_CHARSET, OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS,
        DEFAULT_QUALITY, DEFAULT_PITCH | FF_DONTCARE, "CS2 Gun Icons");

    return true;
}

bool InitUDP() {
    WSADATA wsa;
    if (WSAStartup(MAKEWORD(2, 2), &wsa) != 0) return false;

    g_sock = socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
    if (g_sock == INVALID_SOCKET) return false;

    int rcvbuf = 131072;
    setsockopt(g_sock, SOL_SOCKET, SO_RCVBUF, (const char*)&rcvbuf, sizeof(rcvbuf));

    sockaddr_in addr{};
    addr.sin_family      = AF_INET;
    addr.sin_addr.s_addr = inet_addr("127.0.0.1");
    addr.sin_port        = htons(7777);
    if (bind(g_sock, (sockaddr*)&addr, sizeof(addr)) == SOCKET_ERROR) return false;

    u_long mode = 1;
    ioctlsocket(g_sock, FIONBIO, &mode);

    InitializeCriticalSection(&g_cs);
    InitializeCriticalSection(&g_csWin);
    return true;
}

void CleanupD3D() {
    if (g_pDevice)   { g_pDevice->Release();    g_pDevice   = nullptr; }
    if (g_hFont)     { DeleteObject(g_hFont);    g_hFont     = nullptr; }
    if (g_hIconFont) { DeleteObject(g_hIconFont); g_hIconFont = nullptr; }
    RemoveFontResourceExA("weapon_font.ttf", FR_PRIVATE, 0);
    if (g_pD3D)      { g_pD3D->Release();       g_pD3D      = nullptr; }
    if (g_sock != INVALID_SOCKET) { closesocket(g_sock); g_sock = INVALID_SOCKET; }
    DeleteCriticalSection(&g_cs);
    DeleteCriticalSection(&g_csWin);
    WSACleanup();
}

void PollUDP() {
    if (g_sock == INVALID_SOCKET) return;

    char buf[65536];
    sockaddr_in from{};
    int fromlen = sizeof(from);
    int ret;

    std::vector<LineCmd> newLines;
    std::vector<RectCmd> newRects;
    std::vector<TextCmd> newTexts;
    bool gotData = false;

    while ((ret = recvfrom(g_sock, buf, sizeof(buf), 0,
                           (sockaddr*)&from, &fromlen)) > 0) {
        newLines.clear();
        newRects.clear();
        newTexts.clear();
        gotData = true;

        const uint8_t* p   = (const uint8_t*)buf;
        const uint8_t* end = p + ret;

        while (p < end) {
            uint8_t cmdType = *p;

            if (cmdType == CMD_LINE) {
                if (p + sizeof(BinLine) > end) break;
                const BinLine* cmd = (const BinLine*)p;
                newLines.push_back({cmd->x1, cmd->y1, cmd->x2, cmd->y2,
                                    (D3DCOLOR)cmd->color, cmd->thickness});
                p += sizeof(BinLine);
            }
            else if (cmdType == CMD_RECT) {
                if (p + sizeof(BinRect) > end) break;
                const BinRect* cmd = (const BinRect*)p;
                newRects.push_back({cmd->x1, cmd->y1, cmd->x2, cmd->y2,
                                    (D3DCOLOR)cmd->color});
                p += sizeof(BinRect);
            }
            else if (cmdType == CMD_TEXT) {
                if (p + sizeof(BinTextHdr) > end) break;
                const BinTextHdr* hdr = (const BinTextHdr*)p;
                if (p + sizeof(BinTextHdr) + hdr->textLen > end) break;
                TextCmd t;
                t.x     = hdr->x;
                t.y     = hdr->y;
                t.size  = hdr->size;
                t.color = (D3DCOLOR)hdr->color;
                t.icon  = (hdr->icon != 0);
                t.text  = std::string((const char*)(p + sizeof(BinTextHdr)), hdr->textLen);
                newTexts.push_back(t);
                p += sizeof(BinTextHdr) + hdr->textLen;
            }
            else if (cmdType == CMD_GAME_WIN) {
                if (p + sizeof(BinGameWin) > end) break;
                const BinGameWin* cmd = (const BinGameWin*)p;
                EnterCriticalSection(&g_csWin);
                g_GameX = cmd->x; g_GameY = cmd->y;
                g_GameW = cmd->w; g_GameH = cmd->h;
                g_GameWindowDirty = true;
                LeaveCriticalSection(&g_csWin);
                p += sizeof(BinGameWin);
            }
            else {
                break;
            }
        }
    }

    if (gotData) {
        EnterCriticalSection(&g_cs);
        g_lines.swap(newLines);
        g_rects.swap(newRects);
        g_texts.swap(newTexts);
        g_DataDirty = true;
        LeaveCriticalSection(&g_cs);
    }
}

static void DrawTextGDI(HDC hdc, const std::vector<TextCmd>& texts) {
    SetBkMode(hdc, TRANSPARENT);
    for (const auto& t : texts) {
        int x = (int)(t.x - g_VirtualX);
        int y = (int)(t.y - g_VirtualY);
        HFONT prev = (HFONT)SelectObject(hdc,
            (t.icon && g_hIconFont) ? g_hIconFont : g_hFont);
        BYTE cr = (BYTE)((t.color >> 16) & 0xFF);
        BYTE cg = (BYTE)((t.color >>  8) & 0xFF);
        BYTE cb = (BYTE)( t.color        & 0xFF);
        SetTextColor(hdc, RGB(cr, cg, cb));
        TextOutA(hdc, x, y, t.text.c_str(), (int)t.text.size());
        if (prev) SelectObject(hdc, prev);
    }
}

void RenderFrame() {
    if (!g_pDevice) return;

    g_pDevice->Clear(0, nullptr, D3DCLEAR_TARGET,
        D3DCOLOR_XRGB(0, 0, 0), 1.0f, 0);

    std::vector<LineCmd> linesCopy;
    std::vector<RectCmd> rectsCopy;
    std::vector<TextCmd> textsCopy;
    EnterCriticalSection(&g_cs);
    linesCopy = g_lines;
    rectsCopy = g_rects;
    textsCopy = g_texts;
    LeaveCriticalSection(&g_cs);

    const float vx = (float)g_VirtualX;
    const float vy = (float)g_VirtualY;

    if (SUCCEEDED(g_pDevice->BeginScene())) {

        if (!rectsCopy.empty()) {
            std::vector<TLVERTEX> rv;
            rv.reserve(rectsCopy.size() * 6);
            for (const auto& rc : rectsCopy) {
                float x1 = rc.x1 - vx, y1 = rc.y1 - vy;
                float x2 = rc.x2 - vx, y2 = rc.y2 - vy;
                TLVERTEX v; v.z = 0; v.rhw = 1; v.color = rc.color;
                v.x = x1; v.y = y1; rv.push_back(v);
                v.x = x2; v.y = y1; rv.push_back(v);
                v.x = x1; v.y = y2; rv.push_back(v);
                v.x = x2; v.y = y1; rv.push_back(v);
                v.x = x2; v.y = y2; rv.push_back(v);
                v.x = x1; v.y = y2; rv.push_back(v);
            }
            g_pDevice->DrawPrimitiveUP(D3DPT_TRIANGLELIST,
                (UINT)(rv.size() / 3), rv.data(), sizeof(TLVERTEX));
        }

        std::vector<TLVERTEX> thinV, thickV;
        for (const auto& ln : linesCopy) {
            if (ln.thickness <= 1.5f) {
                TLVERTEX a, b;
                a.x = ln.x1 - vx; a.y = ln.y1 - vy; a.z = 0; a.rhw = 1; a.color = ln.color;
                b.x = ln.x2 - vx; b.y = ln.y2 - vy; b.z = 0; b.rhw = 1; b.color = ln.color;
                thinV.push_back(a);
                thinV.push_back(b);
            } else {
                float dx = ln.x2 - ln.x1, dy = ln.y2 - ln.y1;
                float len = sqrtf(dx * dx + dy * dy);
                if (len < 0.001f) continue;
                float half = ln.thickness * 0.5f;
                float nx = (-dy / len) * half;
                float ny = ( dx / len) * half;
                float ax = ln.x1 - vx, ay = ln.y1 - vy;
                float bx = ln.x2 - vx, by = ln.y2 - vy;
                TLVERTEX v; v.z = 0; v.rhw = 1; v.color = ln.color;
                v.x = ax + nx; v.y = ay + ny; thickV.push_back(v);
                v.x = ax - nx; v.y = ay - ny; thickV.push_back(v);
                v.x = bx + nx; v.y = by + ny; thickV.push_back(v);
                v.x = ax - nx; v.y = ay - ny; thickV.push_back(v);
                v.x = bx - nx; v.y = by - ny; thickV.push_back(v);
                v.x = bx + nx; v.y = by + ny; thickV.push_back(v);
            }
        }
        if (!thinV.empty())
            g_pDevice->DrawPrimitiveUP(D3DPT_LINELIST,
                (UINT)(thinV.size() / 2), thinV.data(), sizeof(TLVERTEX));
        if (!thickV.empty())
            g_pDevice->DrawPrimitiveUP(D3DPT_TRIANGLELIST,
                (UINT)(thickV.size() / 3), thickV.data(), sizeof(TLVERTEX));

        g_pDevice->EndScene();
    }

    g_pDevice->Present(nullptr, nullptr, nullptr, nullptr);

    if (!textsCopy.empty()) {
        HDC hdc = GetDC(g_hWnd);
        if (hdc) {
            DrawTextGDI(hdc, textsCopy);
            ReleaseDC(g_hWnd, hdc);
        }
    }
}

int WINAPI WinMain(HINSTANCE hInst, HINSTANCE, LPSTR, int) {
    int vx = GetSystemMetrics(SM_XVIRTUALSCREEN);
    int vy = GetSystemMetrics(SM_YVIRTUALSCREEN);
    int vw = GetSystemMetrics(SM_CXVIRTUALSCREEN);
    int vh = GetSystemMetrics(SM_CYVIRTUALSCREEN);
    g_VirtualX = vx;
    g_VirtualY = vy;

    WNDCLASSEX wc{};
    wc.cbSize        = sizeof(WNDCLASSEX);
    wc.style         = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc   = WndProc;
    wc.hInstance      = hInst;
    wc.hCursor       = LoadCursor(nullptr, IDC_ARROW);
    wc.lpszClassName = L"D3DOverlayClass";
    if (!RegisterClassEx(&wc)) return 0;

    g_hWnd = CreateWindowEx(
        WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT,
        wc.lpszClassName, L"D3DOverlay", WS_POPUP,
        vx, vy, vw, vh,
        nullptr, nullptr, hInst, nullptr);
    if (!g_hWnd) return 0;

    SetLayeredWindowAttributes(g_hWnd, RGB(0, 0, 0), 0, LWA_COLORKEY);
    ShowWindow(g_hWnd, SW_SHOW);
    UpdateWindow(g_hWnd);

    if (!InitD3D(g_hWnd) || !InitUDP()) {
        CleanupD3D();
        return 0;
    }

    MSG msg{};
    while (g_Running) {
        while (PeekMessage(&msg, nullptr, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) g_Running = false;
            TranslateMessage(&msg);
            DispatchMessage(&msg);
        }

        PollUDP();

        EnterCriticalSection(&g_csWin);
        if (g_GameWindowDirty && g_GameW > 0 && g_GameH > 0) {
            SetWindowPos(g_hWnd, HWND_TOPMOST,
                g_GameX, g_GameY, g_GameW, g_GameH,
                SWP_NOACTIVATE);
            g_VirtualX = g_GameX;
            g_VirtualY = g_GameY;

            D3DPRESENT_PARAMETERS d3dpp{};
            d3dpp.Windowed            = TRUE;
            d3dpp.SwapEffect          = D3DSWAPEFFECT_DISCARD;
            d3dpp.hDeviceWindow       = g_hWnd;
            d3dpp.BackBufferFormat    = D3DFMT_A8R8G8B8;
            d3dpp.BackBufferWidth     = g_GameW;
            d3dpp.BackBufferHeight    = g_GameH;
            if (SUCCEEDED(g_pDevice->Reset(&d3dpp))) {
                g_pDevice->SetRenderState(D3DRS_ALPHABLENDENABLE, TRUE);
                g_pDevice->SetRenderState(D3DRS_SRCBLEND,  D3DBLEND_SRCALPHA);
                g_pDevice->SetRenderState(D3DRS_DESTBLEND, D3DBLEND_INVSRCALPHA);
                g_pDevice->SetFVF(D3DFVF_TLVERTEX);
            }

            g_GameWindowDirty = false;
        }
        LeaveCriticalSection(&g_csWin);

        if (g_DataDirty) {
            RenderFrame();
            g_DataDirty = false;
        }
        Sleep(1);
    }

    CleanupD3D();
    return 0;
}
