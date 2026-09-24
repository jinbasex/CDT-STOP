# CDT-STOP
这是一个简单的CDT监控脚本
##它有什么效果
当达到设定额度的时候会自行关闭主机，等到账单重置就会自动开机
**请注意CDT 有两单三小时的账单延迟**

##如何使用
请使用python3运行

并且请补充需要的依赖

```
apt update && apt install python3-pip -y
pip3 install requests aliyun-python-sdk-core aliyun-python-sdk-ecs --break-system-packages
```


请在config.json填写所需的值 然后通过nohp 或者systemctl 来进行脚本的使用 

```nohup python3 jiankong.py > monitor.log 2>&1 &```


```
[Unit]
Description=Aliyun ECS Monitor Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
# 指定工作目录，确保能正确读取到 config.json
WorkingDirectory=/home/alicdt
# 执行启动命令并把输出追加到你原来的日志文件中
ExecStart=/bin/sh -c '/usr/bin/python3 -u jiankong.py >> /home/alicdt/monitor.log 2>&1'
# 遇到意外崩溃时自动重启服务
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target

```
