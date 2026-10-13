import json
import sys
import time
from pathlib import Path

from .desktop import create_desktop, profile_problem


def calibrate(profile_path):
    import tkinter as tk
    from PIL import ImageTk
    driver = create_desktop({})
    if sys.platform == "darwin":
        allowed, detail = driver.native.permissions()
        if not allowed:
            raise RuntimeError(detail)
    if not driver.unlocked():
        raise RuntimeError("请先解锁发送电脑并打开企业微信")
    hwnd = driver.find_window()
    driver._foreground(hwnd)
    time.sleep(0.5)
    image = driver.capture_window(hwnd)
    width, height = image.size
    root = tk.Tk()
    root.title("企微发送端 · 界面校准")
    root.attributes("-topmost", True)
    screen_w, screen_h = root.winfo_screenwidth(), root.winfo_screenheight()
    scale = min(1, (screen_w-100)/width, (screen_h-180)/height)
    resized = image.resize((int(width*scale),int(height*scale)))
    picture = ImageTk.PhotoImage(resized)
    help_text = tk.StringVar()
    font = "PingFang SC" if sys.platform == "darwin" else "Microsoft YaHei"
    tk.Label(root,textvariable=help_text,font=(font,12),wraplength=max(300,int(width*scale)-40),justify="left",padx=15,pady=15).pack(fill="x")
    canvas = tk.Canvas(root,width=picture.width(),height=picture.height(),highlightthickness=0,cursor="crosshair")
    canvas.pack()
    picture_id = canvas.create_image(0,0,image=picture,anchor="nw")
    instructions = [
        ("search_point","point","第 1/5 步：点击企微左上角的全局搜索输入框。"),
        ("results_rect","rect","第 2/5 步：框选搜索结果中的完整群名和人数所在区域，排除“外部”标签、时间及输入框；以搜索弹层实际位置为准。"),
        ("header_rect","rect","第 3/5 步：拖动框选右侧聊天顶部的完整群名称区域，包含群名和人数即可。"),
        ("input_point","point","第 4/5 步：点击右下方消息输入区的中间位置。"),
        ("messages_rect","rect","第 5/5 步：拖动框选聊天消息显示区，必须排除下面的消息输入框和顶部群标题。"),
    ]
    profile = {"platform":sys.platform,"window_size":[width,height],"idle_seconds":3,"search_wait_seconds":2.5,"send_shortcut":"enter","confirmation_seconds":18}
    saved = [False]
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
        profile[key]=value;start[0]=None
        problem=profile_problem(profile,complete=False)
        if problem:
            from tkinter import messagebox
            profile.pop(key,None)
            messagebox.showwarning("请调整校准范围",problem+"\n可以点击“上一步”重新选择之前的区域。",parent=root)
            return
        current[0]+=1
        if current[0]==len(instructions):
            from tkinter import messagebox
            if messagebox.askyesno("发送快捷键","企微中是否按 Enter 发送消息？\n请按企微设置中的实际选项回答。",parent=root):profile["send_shortcut"]="enter"
            elif sys.platform == "darwin":
                profile["send_shortcut"] = ("cmd-enter" if messagebox.askyesno(
                    "Mac 组合快捷键","是否使用 Command（⌘）+Enter 发送？\n选择“否”则使用 Ctrl+Enter。",parent=root) else "ctrl-enter")
            else:profile["send_shortcut"]="ctrl-enter"
            target=Path(profile_path);target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding="utf-8")
            saved[0] = True
            messagebox.showinfo("校准已保存","校准完成。请保持企微窗口尺寸不变，先用测试群验证发送与回执。",parent=root)
            root.destroy()
        else:help_text.set(instructions[current[0]][2])
    canvas.bind("<ButtonPress-1>",press);canvas.bind("<B1-Motion>",move);canvas.bind("<ButtonRelease-1>",release)
    def previous():
        current[0]=max(0,current[0]-1);start[0]=None
        for key,_,_ in instructions[current[0]:]:profile.pop(key,None)
        if rectangle[0]:canvas.delete(rectangle[0]);rectangle[0]=None
        help_text.set(instructions[current[0]][2])
    tk.Button(root,text="上一步",command=previous,padx=14,pady=5).pack(pady=4)
    def refresh_picture():
        nonlocal picture
        from tkinter import messagebox
        root.withdraw()
        try:
            driver._foreground(hwnd)
            time.sleep(5)
            fresh = driver.capture_window(hwnd)
            if fresh.size != (width, height):
                raise RuntimeError("窗口尺寸已改变，请关闭校准并重新开始")
            picture = ImageTk.PhotoImage(fresh.resize((int(width*scale),int(height*scale))))
            canvas.itemconfigure(picture_id, image=picture)
        except Exception as exc:
            root.deiconify()
            messagebox.showerror("截图未完成",str(exc),parent=root)
        finally:
            root.deiconify()
            root.lift()
    tk.Button(root,text="刷新截图（5 秒后）",command=refresh_picture,padx=14,pady=5).pack(pady=4)
    tk.Label(root,text="校准不会发消息。搜索结果位置不清楚时点“刷新截图”，在 5 秒内打开企微搜索结果。关闭可取消。",font=(font,9),wraplength=max(300,int(width*scale)-40),padx=10,pady=10).pack()
    root.mainloop()
    if not saved[0]:
        raise RuntimeError("界面校准已取消，发送端未启动")
