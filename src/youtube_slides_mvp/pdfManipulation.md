实现对pdf文件指定页面修改，删除，插入等操作，命令行接口如下：

# 删除第 2、5-8、12 页
pdfpages slides.pdf --delete 2,5-8,12 -o slides-1.pdf  --from slides_raw.pdf

# 在第 3 页之后插入另一份 PDF 中由insert指定的页码列表
pdfpages slides.pdf --insert 5,7-9,13 --after 3 -o slides-1.pdf --from slides_raw.pdf 

# 替换第 3、7 页为第4、8页
pdfpages slides.pdf --replace 3,7:4,8 -o slides-1.pdf --from slides_raw.pdf

# 按视频时间定位 source 页码（source 侧支持 @时间 语法）
pdfpages slides.pdf --insert @00:12:34-@00:12:50 --after 17 -o slides-1.pdf --from-run runs/<task>
pdfpages slides.pdf --replace 12:@754.5s -o slides-1.pdf --from-run runs/<task>

# 一次执行里组合 delete / insert / replace（全部按原始页码解释）
pdfpages slides.pdf --delete 2,5-8,12 --insert 5,7-9,13 --after 3 --replace 3,7:4,8 -o slides-1.pdf --from slides_raw.pdf

# 多条 insert，每条 insert 后面都跟一个 after
pdfpages slides.pdf --insert 2 --after 1 --insert 4-5 --after 3 -o slides-1.pdf --from slides_raw.pdf


支持以下灵活写法（业界最佳实践）：

3                    → 第 3 页
3-7                  → 第 3 到 7 页
3,5,7                → 第 3、5、7 页
5-                   → 第 5 页到最后
-5                   → 前 5 页
1,3-5,8-             → 组合写法
last 或 -1         → 最后一页

时间定位写法使用 `@时间`，例如 `@754.5s`、`@12:34`、`@01:02:03.500`、`@12:34-@12:50`。如果没有显式传 `--from-run`，CLI 会沿着当前 input PDF 所在目录向上查找 run 上下文，并自动找到源 PDF 和时间索引。

组合模式下，不会按中间态重新编号：delete 和 replace 仍然命中原始输入页码，insert 的 after 也按原始页边界解释。
`--insert` 可以重复出现，但每一条后面必须紧跟 `--after`。