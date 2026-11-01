# Google Sites → GitHub Pages

日常维护：在 Google Sites 编辑 → 点击“发布”。程序约每两小时读取已发布内容，并更新 https://junzhousoc.github.io/ 。不读取草稿，不需要共享 Google 密码或 GitHub 密码。

来源：https://sites.google.com/view/jun-zhou-

目标仓库：https://github.com/junzhousoc/junzhousoc.github.io （默认分支 master）

## 首次启用

1. 仓库拥有者将维护者的 GitHub 账号添加为 Collaborator，维护者接受邀请。把此目录里的文件添加到仓库 master 分支，尤其要包含隐藏目录 `.github/workflows/`。保留原有文件即可，部署仅使用 `site/`。
2. 仓库拥有者在 Settings → Pages → Build and deployment → Source 中选择 **GitHub Actions**。Custom domain 应为空，使用 github.io 地址。此包不生成 CNAME 文件，也不修改域名续费设置。
3. 在 Actions 中打开 **Sync Google Sites to GitHub Pages** → **Run workflow**。首次执行成功后，打开 https://junzhousoc.github.io/ 检查各页面、图片及 CV。如果仓库有分支保护阻止机器人写入，需要拥有者调整规则或将“保存历史”步骤改为 PR 流程；不要把检查失败改成忽略。

同步程序使用 GitHub 自动提供的 GITHUB_TOKEN，无须另存个人访问令牌。若通过第三方 GitHub 连接代为上传，还需该连接有目标仓库及 workflow 文件的写入权限；被邀请为协作者并不自动授予第三方应用访问权限。

## 自动同步的行为

- 每两小时的第 23 分钟运行一次（UTC）；GitHub 可能延迟执行，并非即时发布。
- 从公开发布站点的导航及正文链接发现页面，保留页面内容、原站样式及字体；图片、样式和字体保存为本地文件。
- 将源站和旧域名的内部链接改为 GitHub Pages 相对路径。首页与各栏目均可直接打开。
- 只有完成所有页面和资源下载后才生成完整发布包；失败会阻止部署，线上保留上一版。
- 新内容保存到 `site/` 并提交到仓库，保留历史。文件按内容计算摘要，Google 临时图片 URL 改变不导致图片文件名改变。
- CV 等 Google Drive 嵌入仍由 Google 提供，并附有单独打开的链接。请保持原文件的公开访问权限。
- 固定保护五个已有栏目；如果有意删除或改名，需要同步修改 `sync-config.json` 的 `required_pages`。新增导航栏目会自动发现。

## 长期运行与故障

GitHub 公开仓库在 60 天没有仓库活动后会自动停用定时工作流。本流程每个 UTC 月自动写入并提交一次 `.sync/health.json`，记录该月首次检查时间和源站同步结果；即使网站内容不变，也会产生定期仓库活动，无需你们定期登录或提交。一个月内的其他运行不重复修改记录。源站同步失败时仍记录当月健康状态，但不会发布不完整的网站。此机制沿用现有自动令牌，不需要外部定时服务、个人访问令牌或本地电脑在线。

在 GitHub 的通知设置中开启 Actions 失败通知，关注最新一次工作流结果。若 GitHub 改动默认分支名，请修改 workflow 中的 `push.branches`。

健康记录可避免因内容不更新造成的闲置停用，但权限撤销、GitHub 服务或规则变化、Google 页面结构变化仍可能需要处理；这不是永久零维护保证。

Google Sites 没有支持新版站点的官方内容 API；此工具解析已发布的 HTML。Google 若改变结构，可能需要维护解析器。当前版本去除 Google Sites 应用脚本，提供独立静态导航，字体采用原站的 Lato 16px：普通栏目字重 300，当前栏目字重 400，无下划线；内置搜索、轮播、折叠控件等依赖 Google 脚本的交互不会自动移植。新增这类组件后应先适配并验收。

源站必须持续公开发布在上述 sites.google.com 地址。旧域名可以到期停用，同步与它无关；已散发的旧域名链接在到期后也不会继续跳转。

## 本地验证

Python 3.9+：

```sh
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s scripts -p 'test_*.py'
python3 scripts/sync.py
python3 -m http.server --directory site
```

输出目录默认是 `site/`，可用 `--output` 指定新的目录。不要手动修改 `site/` 中的内容，下次同步会覆盖它；修改 Google Sites 或转换程序。

## 参考

- https://developers.google.com/workspace/sites
- https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
