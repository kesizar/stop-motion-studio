# 定格动画工作台

固定镜头，让文具、积木或纸片一点点移动。每次摆好道具并收回手，工作台会在画面稳定后收下一张。连续回放这些照片，就得到一段定格动画。

## 开始使用

Windows 电脑使用带 Tcl/Tk 的 64 位 Python 3.10–3.12，推荐 Python 3.11。双击同目录的 **启动工作台.cmd**。首次启动会在项目的 `.venv` 中安装依赖，需要联网。项目附带 Google 的手部模型 hand_landmarker.task。以后可离线拍摄。

1. 第一次体验可以点「试用演示」，或直接双击 **体验模拟拍摄.cmd**。纸船、水面和手部信号均由程序生成，使用与实拍相同的自动快门。模拟帧存于临时目录，离开演示前可导出 GIF。
2. 实拍时固定摄像头，朝向桌面，保持光线稳定。选摄像头编号，摆好第一帧后开始拍摄。静止片刻，第一张照片会出现在时间轴上。
3. 让手清楚地进入取景区，移动道具一点，再把手完全移开。等帧数增加再摆下一次。收手后画面持续晃动时系统会等待。仅伸手又收回且场景没有显著变化时会跳过。
4. 点撤回可删除当前作品的最后一帧。选回放速度并回放，或者导出循环 GIF。点「新建项目」开始下一部动画，旧作品原图保留在 `作品` 目录。关闭程序后再打开可以继续最近的实拍作品。

打开摄像头失败时，先关闭占用设备的软件，确认 Windows 的相机隐私设置允许桌面应用访问，再试其他编号。USB 摄像头更容易固定俯拍，笔记本内置摄像头也可以拍正对镜头的小场景。

## 自动拍摄如何判断

实拍使用 MediaPipe Hand Landmarker 在每张视频画面中寻找手部关键点。Python 用手是否出现、连续画面是否稳定、当前画面与上一张照片是否有局部变化作出拍摄决定。首次稳定取景建立第一帧。之后一次伸手和离手最多对应一次收帧。保存的是摄像头原始画面。

手在模型视野外、光线太暗、道具和背景颜色接近、仅移动不到几个像素，都可能让本次判断失效。先用背景单一、颜色反差明显的道具测试。

## 演示与验证

正式拍摄可以用两块橡皮，逐帧演示其中一块绕过另一块。向观众展示三个动作：伸手后原样收回，移动道具后让桌面晃动，最后把道具摆稳。观察前两步是否跳过或等待、第三步是否收帧。连续拍六到十张后回放，再导出 GIF。

已安装依赖后，在项目目录的 PowerShell 中运行：

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

`app.py` 连接摄像头、快门、时间轴与作品存储；`sources.py` 提供摄像头和模拟画面；`shutter.py` 负责自动快门；`studio_ui.py` 提供中文界面；`sessions.py` 保存帧与导出 GIF。研究或答辩时可以分别验证模拟场景、真实光照下的手部检测、完整的相机到成片流程。

第三方依赖包括 MediaPipe Hand Landmarker、OpenCV、NumPy、Pillow 和 Python 标准库 Tkinter。[MediaPipe Hand Landmarker 概述](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python) · [本项目使用的 MediaPipe 版本](https://pypi.org/project/mediapipe/0.10.21/)

手部模型取自 [Google 发布的模型文件（float16，版本 1）](https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task)。应用将模型读取为字节后再交给 MediaPipe，支持中文项目路径。
