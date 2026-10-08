# 第二十八步：快捷修图布局与退出修复

2026-10-04。用户截图反馈，复现并修复三项确认问题。

- P2 长图溢出：原1280×2778截图在280px网格预览框内显示819.28px高，覆盖下载、操作和记录。图片百分比max-height不足以约束网格自动最小尺寸。明确网格minmax(0,1fr)、图片宽高100%与min-size0，contain保持比例，overflow作为额外边界。桌面真实图修复后图片元素262px高，位于280px预览框内；390×844下182px高位于200px框内。
- P2 放大弹窗Esc串联关闭编辑器：cancel事件沿React父链传播。细节弹窗preventDefault/stopPropagation，只关闭自身。真实浏览器Esc后editorStillOpen=true、detailClosed=true，新增真实组件嵌套事件回归。
- P2 窄屏图片项目列表隐藏聊天：700px样式用last-child隐藏用于聊天按钮，无项目时误命中聊天导航。改成明确canvas-send-to-chat类，仅隐藏辅助发送按钮；390px列表聊天按钮可见并可返回。

23项相关前端、生产构建通过。原生同一用户截图/既有结果复验桌面、窄屏、放大退出；未执行新修图、无模型调用、未改变商品正式成果。保存outputs/image-layout-fixed-desktop.png与image-layout-fixed-mobile.png。默认viewport已恢复。

本次修复确认的三个问题，不宣称系统所有bug清零。长截图现在按完整原图适配，商品较小可用放大或完整画布裁剪；没有擅自裁切用户源文件。
