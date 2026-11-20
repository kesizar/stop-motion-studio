# 定格动画工作台

固定镜头，让文具、积木或纸片一点点移动。每次摆好道具并收回手，工作台会在画面稳定后收下一张。连续回放这些照片，就得到一段定格动画。

## 开始使用

Windows 电脑使用带 Tcl/Tk 的 64 位 Python 3.10–3.12，推荐 Python 3.11。双击同目录的 **启动工作台.cmd**。首次启动会在项目的 `.venv` 中安装依赖，需要联网。项目附带 Google 的手部模型 hand_landmarker.task。以后可离线拍摄。

1. 第一次体验可以点「试用演示」，或直接双击 **体验模拟拍摄.cmd**。纸船、水面和手部信号均由程序生成，使用与实拍相同的自动快门。拍满 8 帧后提示回放。模拟帧存于临时目录，离开演示前可导出 GIF。
2. 实拍时固定摄像头，朝向桌面，保持光线稳定。选摄像头编号，摆好第一帧后开始拍摄。静止片刻，第一张照片会出现在时间轴上。
3. 勾选「上一帧叠影」，可以在实时预览里对照刚拍下的一帧，估计道具挪了多远。保存和导出使用原始画面。
4. 摆好道具后把手移出取景区。取景下方的橙色条显示画面稳定进度，绿色表示刚刚拍到一帧。原样收手且画面无变化时会跳过。
5. 漏了一帧时，点「暂停自动快门」，移开手，再点「手动拍一帧」。点「恢复自动快门」继续自动拍摄。
6. 点撤回可删除当前作品的最后一帧。选回放速度并回放，或者导出循环 GIF。点「新建项目」开始下一部动画。用「打开作品…」选择旧作品，可以继续拍摄、回放和导出。关闭程序后会默认打开编号最新的作品。原图保存在 `作品` 目录。

打开摄像头失败时，先关闭占用设备的软件，确认 Windows 的相机隐私设置允许桌面应用访问，再试其他编号。USB 摄像头更容易固定俯拍，笔记本内置摄像头也可以拍正对镜头的小场景。

## 自动拍摄如何判断

实拍使用 MediaPipe Hand Landmarker 在每张视频画面中寻找手部关键点。Python 用手是否出现、连续画面是否稳定、当前画面与上一张照片是否有局部变化作出拍摄决定。首次稳定取景建立第一帧。之后一次伸手和离手最多对应一次收帧。保存的是摄像头原始画面。

手在模型视野外、光线太暗、道具和背景颜色接近、仅移动不到几个像素，都可能让本次判断失效。先用背景单一、颜色反差明显的道具测试。

## 演示与验证

打开[课堂验收指南](docs/课堂验收.md)，可查看操作步骤、模块分工和六组合成输入的对照结果。

```powershell
.\.venv\Scripts\python.exe -B verify_capture.py
.\.venv\Scripts\python.exe -B -m unittest discover -s tests -v
```

第三方依赖包括 MediaPipe Hand Landmarker、OpenCV、NumPy、Pillow 和 Python 标准库 Tkinter。[MediaPipe Hand Landmarker 概述](https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker/python) · [本项目使用的 MediaPipe 版本](https://pypi.org/project/mediapipe/0.10.21/)

手部模型取自 [Google 发布的模型文件（float16，版本 1）](https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task)。应用将模型读取为字节后再交给 MediaPipe，支持中文项目路径。

随项目分发的手部模型采用 Apache License 2.0。[Google 模型卡](https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Hand%20Tracking%20%28Lite_Full%29%20with%20Fairness%20Oct%202021.pdf) · [模型许可证全文](LICENSE-model.txt)
