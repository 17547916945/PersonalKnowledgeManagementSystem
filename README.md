# 智能个人知识管理系统 (Intelligent Personal Knowledge Management System)

这是一个基于Flask和现代Web技术的智能个人知识管理系统，具有完整的后端API和前端界面，支持多格式文档管理、知识图谱构建、学习分析和智能推荐等功能。

## 功能特性

### 1. 学习概览面板
- 展示关键学习指标（文档总数、总存储空间、平均文档大小等）
- 最近上传的文档展示
- 智能推荐相关内容

### 2. 文档管理面板
- **多格式支持**: TXT、MD、PDF、DOCX、DOC
- **文档上传**: 支持拖拽上传和文件选择
- **文档预览**: 点击文档卡片查看完整内容和详情
- **文档搜索**: 全文搜索功能
- **自动处理**: 自动提取关键词和实体

### 3. 知识图谱面板
- **可视化展示**: 使用ECharts实现交互式知识图谱
- **节点详情**: 点击节点查看详细信息
- **关系展示**: 展示知识点之间的关联关系
- **搜索功能**: 支持按关键词搜索知识点

### 4. 学习分析面板
- **学习时长统计**: 按周/月/季度展示学习时长趋势
- **知识点掌握分布**: 饼图展示已掌握、学习中、待学习的知识点分布
- **学习进展预测**: 基于当前学习进度预测完成时间
- **优化建议**: 系统自动生成个性化学习建议

### 5. 智能推荐
- 基于文档关键词的相似文档推荐
- 基于用户行为的个性化推荐

## 技术栈

### 后端
- **Python 3.8+**
- **Flask**: Web框架
- **SQLite**: 数据库
- **spaCy**: 自然语言处理
- **scikit-learn**: 机器学习算法
- **NetworkX**: 图数据处理
- **PyPDF2**: PDF文件处理
- **python-docx**: Word文档处理

### 前端
- **HTML5/CSS3/JavaScript**
- **Tailwind CSS**: 样式框架
- **ECharts**: 数据可视化
- **Iconify**: 图标库

## 安装和运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 下载spaCy中文模型（可选，用于更好的中文处理）

```bash
python -m spacy download zh_core_web_sm
```

如果无法下载中文模型，系统会使用基础文本处理功能。

### 3. 运行应用

```bash
python app.py
```

### 4. 访问系统

在浏览器中打开: `http://localhost:5000`

## 项目结构

```
.
├── app.py                      # Flask应用主文件
├── requirements.txt            # Python依赖包
├── README.md                   # 项目说明文档
├── data/
│   └── knowledge.db           # SQLite数据库
├── uploads/                    # 上传文件存储目录
├── templates/
│   ├── index.html             # 主页面模板
│   └── knowledge_graph.html    # 知识图谱页面模板
└── 需求分析.md                 # 需求分析文档
```

## API接口

### 文档管理
- `GET /api/documents` - 获取文档列表
- `POST /api/documents` - 上传文档
- `GET /api/documents/<id>` - 获取文档详情
- `DELETE /api/documents/<id>` - 删除文档
- `GET /api/search?q=<query>` - 搜索文档

### 知识图谱
- `GET /api/knowledge-graph` - 获取知识图谱数据
- `GET /api/knowledge-graph/search?q=<query>` - 搜索知识图谱

### 学习分析
- `GET /api/analytics/study-time?period=<week|month|quarter>` - 获取学习时长统计
- `GET /api/analytics/knowledge-level` - 获取知识点掌握分布
- `GET /api/analytics/prediction` - 获取学习进展预测

### 推荐系统
- `GET /api/recommendations/<user_id>` - 获取个性化推荐

### 系统信息
- `GET /api/system-info` - 获取系统信息

## 功能说明

### 文档上传和处理
1. 点击"添加文档"按钮或拖拽文件到上传区域
2. 系统自动识别文件类型并提取内容
3. 使用AI技术提取关键词和实体
4. 自动创建知识节点并建立关联

### 知识图谱
- 系统自动从文档中提取关键词作为知识节点
- 节点大小反映出现频率
- 点击节点可查看详细信息
- 支持拖拽和缩放操作

### 学习分析
- 基于文档上传时间和数量生成学习时长统计
- 根据知识节点数量计算掌握度分布
- 使用算法预测学习进度和完成时间

## 注意事项

1. **文件大小限制**: 单个文件最大16MB
2. **支持格式**: TXT、MD、PDF、DOCX、DOC
3. **数据库**: 使用SQLite，数据存储在`data/knowledge.db`
4. **上传文件**: 存储在`uploads/`目录

## 浏览器兼容性

推荐使用以下浏览器的最新版本：
- Chrome 80+
- Firefox 75+
- Edge 80+
- Safari 13+

## 开发说明

### 数据库结构
- `documents`: 文档表
- `knowledge_nodes`: 知识节点表
- `knowledge_edges`: 知识边（关系）表
- `user_behaviors`: 用户行为表

### 扩展功能
- 可以添加用户认证系统
- 可以集成更强大的AI模型
- 可以添加文档编辑功能
- 可以支持更多文件格式

## 许可证

此项目仅供学习和参考使用。