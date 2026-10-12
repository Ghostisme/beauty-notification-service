import json
import time
from pathlib import Path

from .desktop import WindowsDesktop


def calibrate(profile_path):
    import tkinter as tk
    from PIL import ImageTk
    driver = WindowsDesktop({})
    if not driver.unlocked():
        raise RuntimeError("请先解锁 Windows 并打开企业微信")
    hwnd = driver.find_window()
    driver._foreground(hwnd)
    time.sleep(0.5)
    rect = driver.win32gui.GetWindowRect(hwnd)
    image = driver.grab(bbox=rect, all_screens=True)
    width, height = image.size
    root = tk.Tk()
    root.title("企微发送端 · 界面校准")
    root.attributes("-topmost", True)
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    scale = min(1, (screen_w-100)/width, (screen_h-180)/height)
    resized = image.resize((int(width*scale),int(height*scale)))
    picture = ImageTk.PhotoImage(resized)
    help_text = tk.StringVar()
    tk.Label(root,textvariable=help_text,font=("Microsoft YaHei",12),wraplength=int(width*scale)-40,justify="left",padx=15,pady=15).pack(fill="x")
    canvas = tk.Canvas(root,width=picture.width(),height=picture.height(),highlightthickness=0,cursor="crosshair")
    canvas.pack()
    canvas.create_image(0,0,image=picture,anchor="nw")
    instructions = [
        ("search_point","point","第 1/5 步：点击企微左上角的全局搜索输入框。"),
        ("results_rect","rect","第 2/5 步：拖动框选搜索结果会显示的区域（左侧列表），不要包含右侧聊天内容。"),
        ("header_rect","rect","第 3/5 步：拖动框选右侧聊天顶部的完整群名称区域，包含群名和人数即可。"),
        ("input_point","point","第 4/5 步：点击右下方消息输入区的中间位置。"),
        ("messages_rect","rect","第 5/5 步：拖动框选聊天消息显示区，必须排除下面的消息输入框和顶部搜索结果。"),
    ]
    profile = {"window_size":[width,height],"idle_seconds":3,"search_wait_seconds":2.5,"send_shortcut":"enter","confirmation_seconds":18}
    current, start, rectangle = [0], [None], [None]
    help_text.set(instructions[0][2])
    def press(event):
        start[0]=(event.x,event.y)
        if rectangle[0]:canvas.delete(rectangle[0])
    def move(event):
        if start[0] and instructions[current[0]][1]=="rect":
            if rectangle[0]:canvas.delete(rectangle[0])
            rectangle[0]=canvas.create_rectangle(*start[0],event.x,event.y,outline="#1aab81",width=3)
    def release(event):
        if start[0] is None:return
        key,kind,_=instructions[current[0]]
        if kind=="point":value=[round(event.x/scale),round(event.y/scale)]
        else:
            x1,y1=start[0];x2,y2=event.x,event.y
            if abs(x2-x1)<20 or abs(y2-y1)<15:return
            value=[round(min(x1,x2)/scale),round(min(y1,y2)/scale),round(max(x1,x2)/scale),round(max(y1,y2)/scale)]
        profile[key]=value;current[0]+=1;start[0]=None
        if current[0]==len(instructions):
            from tkinter import messagebox
            if messagebox.askyesno("发送快捷键","企微中是否按 Enter 发送消息？\n选择“否”则使用 Ctrl+Enter。",parent=root):profile["send_shortcut"]="enter"
            else:profile["send_shortcut"]="ctrl-enter"
            target=Path(profile_path);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding="utf-8")
            messagebox.showinfo("校准已保存","校准完成。请保持企微窗口尺寸不变，先用测试群验证发送与回执。",parent=root)
            root.destroy()
        else:help_text.set(instructions[current[0]][2])
    canvas.bind("<ButtonPress-1>",press);canvas.bind("<B1-Motion>",move);canvas.bind("<ButtonRelease-1>",release)
    tk.Label(root,text="校准使用窗口截图，不会向任何群发送消息。关闭窗口可取消。",font=("Microsoft YaHei",9),padx=10,pady=10).pack()
    root.mainloop()
