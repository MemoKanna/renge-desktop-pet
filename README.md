# 莲儿桌宠 · Renge Desktop Pet

用 Python、Pillow 和原生 Win32 绘制的透明桌面宠物。以《悠哉日常大王》的宫内莲华为灵感制作的同人项目，支持平滑走路、眨眼、摸头、飞扑、表情、竖笛、鼠标跟随与系统托盘。

![莲儿桌宠动作预览](docs/preview.png)

## 运行

需要 **Windows 10/11、Python 3.10 或更新版本**。推荐 64 位 Python。窗口、托盘和音频均使用 Windows API，不支持直接在 macOS/Linux 运行。

在项目目录运行：

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe renge_pet.py
```

无需 API Key 或网络连接。首次运行会在程序目录创建 `data/settings.json`，保存位置、大小、音量和互动状态。请放在有写入权限的普通文件夹内。

## 互动

拖动身体可移动桌宠，点击头部或按住头部可摸头；点脚边开始走动。右键打开完整菜单，包含曲目、音量、大小、跟随、休息提醒、原声导入与托盘选项。

快捷键只在桌宠窗口获得焦点时生效，不会全局抢占键盘。

| 按键 | 动作 |
| --- | --- |
| F1 | 问候 |
| F2 / F3 | 吹笛或停止 / 换下一首 |
| F4 | 开关鼠标跟随 |
| F5 | 猜拳小游戏 |
| F6 | 喂糖 |
| F7 | 飞扑 |
| F8 | 切换表情 |
| F9 | 开关说话语音 |
| 空格 | 睡觉 / 醒来 |
| Esc / 关闭窗口 | 收纳进系统托盘 |
| Ctrl+Q | 完全退出 |

托盘图标可叫回桌宠，右键托盘图标可完全退出。再次启动程序也会唤回已经运行的实例。

## 声音与素材

开源版自带本项目合成的《小星星》《两只老虎》和原创《田间小调》。传统旋律的编配与合成实现见 `synth.py`，音符数据在 `assets/music/tracks.json`。

**仓库不附带动画、声优录音、原剧音乐或未获公开再分发授权的音频。** 语音接口和动作同步保留；没有导入语音时显示文字、正常播放动作。

导入自己有权使用的录音：

1. 将 15 秒以内的 PCM16 WAV 放进程序旁的 `voices/`，采样率 8–48 kHz，单声道或双声道。
2. 按动作命名，例如 `打招呼-你好.wav`、`摸头-好舒服.wav`、`飞扑-ダイナマイ.wav`。
3. 右键 → 说话语音 → 重新读取原声包。

支持的前缀为：打招呼、闲聊、摸头、喂糖、飞扑、起床、睡觉、跟随、停下、好奇、开心、休息。横线后的文字作为气泡字幕；同一动作可放多段，自定义录音优先。

飞扑喊声在动作开始约 0.30 秒时提交播放，接近起跳时机；实际出声受音频设备延迟影响。每次飞扑只触发一次，重复按 F7 不会截断。拖动、吹笛、取消动作、静音或收进托盘会停止相应播放。

自定义曲目放入 `music/`，再通过右键菜单重新扫描。支持最长 10 分钟的 PCM16 WAV。导入文件只在本机读取，不会上传。

## 打包 Windows EXE

```powershell
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m PyInstaller --noconfirm renge_pet.spec
```

输出为 `dist/RengeDesktopPet.exe`。把 EXE 放入普通文件夹即可使用；可在资源管理器中右键创建桌面快捷方式。`voices/`、`music/` 和 `data/` 会使用 EXE 旁的目录。

## 开发与检查

```powershell
.venv\Scripts\python.exe -m unittest discover -s tests -v
```

GitHub Actions 在 Windows 上检查动作几何、音频导入/取消、素材清单和实际窗口生命周期。运行检查时会短暂显示测试桌宠，测试数据使用临时目录。

主要模块：`renge_pet.py` 管理窗口与交互，`motion.py` 管理动作状态，`walk_rig.py` / `action_rig.py` 管理关节与姿态，`sprites.py` 管理贴图与过渡，`voice.py` / `music.py` 管理本地音频，`tray.py` 管理托盘。

图集缓存已随仓库提供。修改绑定或表情后，可运行 `python bake_walk_cycle.py` 与 `python bake_acting.py` 重建缓存；飞扑缓存较大，重建可能需要一点时间。

## 许可与贡献

代码采用 [MIT](LICENSE)。角色与原作品的权利归其原权利人，本项目不是官方软件，也未获得官方背书。同人图像、传统曲调和外部素材的边界见 [素材说明](ASSETS.md)。

欢迎提交问题和改进。请勿在 Issue、提交或 PR 中上传账号凭据、本机设置、日志中的个人路径、无权公开的音频或原剧片段。
