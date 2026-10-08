# 第十步：60分样片后的 Skill 筛选与采用

日期：2026-10-03。状态：调研与本次作品采用完成；没有批量安装截图项目，也没有把外部导演 Skill 自动接入产品 Agent。

## 选择依据与实现

用户评价上一版茶杯短片60分：视觉、配音、分镜一般。优先改善真实动作、镜头目的、声音与节奏，再决定UI依赖。截图中的项目主要是库，不是视频制作Skill：

| 项目与官方来源 | 实際用途 | 本次决定 |
|---|---|---|
| [Rough.js](https://github.com/rough-stuff/rough) | 手绘图形 | 不适合当前克制的茶具实拍方向 |
| [shadcn/ui](https://github.com/shadcn-ui/ui) | UI组件 | 后续有复杂交互需求再选择；本次不迁移组件系统 |
| [Radix Colors](https://github.com/radix-ui/colors) | 色板 | 可用于之后补全界面颜色状态；当前保留mono-color色板 |
| [README Stats](https://github.com/anuraghazra/github-readme-stats) | GitHub资料卡 | 不进入创作链路 |
| [Mermaid](https://github.com/mermaid-js/mermaid) | 流程图 | 需要教学图时使用 |
| [Simple Icons](https://github.com/simple-icons/simple-icons) | 品牌图标 | 当前没有新增平台入口需求 |
| [Fontsource](https://github.com/fontsource/fontsource) | 字体包 | 后续部署时评估中文字体与字体自身许可；本次使用已有本机字体 |
| [Markdown Badges](https://github.com/Ileriayo/markdown-badges) | 文档徽章 | 不改善作品品质 |

实际采用的导演资料：

1. [director-skills](https://github.com/0xhughs/director-skills)，MIT，固定提交 `35ca0a2b4cd55b0668aa9ea0f40273324b774bb4`。通过官方skill-installer下载到项目忽略的私有参考目录，阅读路由、shotlist-and-visual-breakdown、style-cinematography-director、prompt-iteration-and-diagnostics及相应摄影/QC资料。落实为六镜头表：每镜头有目的、景别、动作、时长、实际素材起点；不再用三张静态图重复缓推。
2. [tvc-director](https://github.com/Ethanxwang/tvc-director)，MIT，固定提交 `593149aba220361bd2c3e9059516c890081ada00`。同目录保存参考，采用生活场景、产品定格、片尾信息层级的方法。其Nano Banana/Seedance生成流程不适合当前运行时，因此没有照搬执行，也没有声称那些服务已接入。
3. [Remotion Skills](https://github.com/remotion-dev/skills)，只调查，暂不加入另一套渲染器/依赖。现有FFmpeg足以完成本次小片。

引用文件在 `.codex/references/creator-quality-v3/`，保留来源提交、许可与下载目录。只阅读Skill资料，没有执行第三方脚本。没有复制整套导演技能到生产 `skills/`；目前应用里的Chat提示模板只增加镜头目的、景别、动作、台词、素材与连续性要求。完整自动编导仍未实现。

## 材料选择与验收步骤

选择Anna Pou同一厨房/玻璃茶具场景的两段实拍：[8296117](https://www.pexels.com/video/a-person-pouring-tea-8296117/)、[8296134](https://www.pexels.com/video/a-woman-pouring-tea-on-a-glass-8296134/)。按[Pexels许可](https://www.pexels.com/license/)使用和修改，不暗示人物代言。原文件、来源页、许可链接、hash和镜头表保存在 `outputs/tea-film-v3/sources.json`。两段分别含琥珀色与淡色茶汤、不同茶壶；作品是同场景生活方式蒙太奇，不伪装成同一杯连续倒茶，也不是具体商品实测广告。

1. 查 `sources.json` 的来源、hash与六镜头表，再打开两段原片核对作者、茶具、动作与实际取段。
2. 播放新成片，检查动作开场、细节、人物场景与片尾是否形成表达，评估是否仍有重复镜头感。
3. 检查应用Skill列表：不应出现被无声安装的新导演Agent或开启终端工具。
4. 用自己的事实从项目Chat生成分镜，核对是否明确镜头目的与未知素材；主稿仍需编辑采用。

自查结论：本次使用了可核对的方法和素材，并未把搜索到的仓库名称当作成片质量证明。自动素材检索、通用剪辑时间线和自动发布暂缓。
