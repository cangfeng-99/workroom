# Windows、Mac和鸿蒙

当前交付以服务器网页为主：Linux保存账号、项目、任务、规则和交付，成员电脑运行自己的AI工具及授权工作区。浏览器关闭不删除服务器队列；成员电脑关机后，其本机AI不会继续运行。

## 普通使用

Windows、Mac、鸿蒙浏览器访问同一个正式HTTPS域名。用户不需要安装Django、Python或数据库。Mac或鸿蒙输入`127.0.0.1:8011`访问的是各自设备，不是开发者的Windows电脑；多设备使用须先部署正式server版本。

窄屏有「菜单」进入项目列表、工具连接和设置；任务树下方保留可滚动详情和验收入口，触屏可滚动画布。拒绝localStorage时缩放使用默认值，不应中断整个页面。

## 本机开发预览

Windows：根目录`Preview-Server.cmd`。

Mac/Linux：安装Python3.12后，在项目根目录运行：

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r workroom/requirements-server.lock
sh ./Preview-Server.command
```

环境已准备时可直接运行脚本；有执行权限的Mac也可双击`.command`。若下载后丢失执行位，用`sh`运行即可。不复制Windows的`.venv`，不把本机预览脚本当作公开服务器。预览只绑定127.0.0.1，独立数据位于`workroom/data/local-preview/`。

## 本机执行与鸿蒙边界

- Mac：AI工具安装在实际执行的Mac上，通过项目令牌接入；账号、文件授权由该用户管理。
- 鸿蒙：本轮支持路径是网页管理服务器和其他执行机任务。没有声称鸿蒙本机可运行完整Django、Claude Code或任意桌面CLI。
- 鸿蒙原生客户端可以后续使用ArkTS/ArkUI和ArkWeb；原生目录授权、URI持久访问、后台能力需针对设备/SDK单独验证。网页文件选择不等于整个目录的持续读写权限。
- 2GB服务器保持协调与轻量Worker；大型编译、完整开发工具和模型放在用户电脑或独立执行环境，不集中到小主机上。

## 实际验证状态

用户明确暂无Mac/鸿蒙设备。本轮验证使用Windows Chrome和触控/390、768、1440视口模拟；POSIX脚本做语法检查。没有Mac/Safari和鸿蒙/ArkWeb真机结论，没有原生.app/.hap安装包或离线PWA承诺。真机待验项目：登录与Cookie、输入法/键盘、触控缩放、剪贴板、后台恢复、字体和浏览器权限。

依据：[Python on macOS](https://docs.python.org/3.12/using/mac.html)、[ArkWeb](https://developer.huawei.com/consumer/cn/doc/harmonyos-guides/web-page-loading)、[鸿蒙电脑Python支持现状](https://consumer.huawei.com/cn/support/content/zh-cn16051020/)。
