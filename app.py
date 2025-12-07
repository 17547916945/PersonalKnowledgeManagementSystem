#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能个人知识管理系统 - 修复版本
支持PDF、Word、TXT、Markdown等多种文件格式
"""

import os
import sys
import json
import sqlite3
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import hashlib
import mimetypes

# 第三方库导入
from flask import Flask, request, jsonify, render_template, send_file, send_from_directory
from flask_cors import CORS
import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import networkx as nx

# 尝试导入PDF处理库
try:
    import PyPDF2
    PDF_AVAILABLE = True
except ImportError:
    PDF_AVAILABLE = False
    print("警告：未安装PyPDF2，PDF处理功能将受限")

# 尝试导入Word处理库
try:
    from docx import Document
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False
    print("警告：未安装python-docx，Word文档处理功能将受限")

# 配置类
class Config:
    """应用配置类"""
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'dev-secret-key-change-in-production'
    DATABASE_PATH = os.path.join(os.path.dirname(__file__), 'data', 'knowledge.db')
    UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB
    
    # AI模型配置
    NLP_MODEL = 'zh_core_web_sm'  # 中文模型
    SIMILARITY_THRESHOLD = 0.3    # 相似度阈值
    
    @staticmethod
    def init_app(app):
        """初始化应用配置"""
        # 创建必要的目录
        os.makedirs(os.path.dirname(Config.DATABASE_PATH), exist_ok=True)
        os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)

# 文档处理工具类
class DocumentProcessor:
    """文档处理工具类 - 支持多种文件格式"""
    
    @staticmethod
    def extract_text_from_txt(file_path: str) -> str:
        """从文本文件提取内容"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                return f.read()
        except UnicodeDecodeError:
            # 尝试其他编码
            with open(file_path, 'r', encoding='gbk') as f:
                return f.read()
    
    @staticmethod
    def extract_text_from_pdf(file_path: str) -> str:
        """从PDF文件提取内容"""
        if not PDF_AVAILABLE:
            return "[PDF处理功能需要安装PyPDF2库]"
        
        try:
            text = ""
            with open(file_path, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                for page in reader.pages:
                    text += page.extract_text() + "\n"
            return text
        except Exception as e:
            return f"[PDF处理错误: {str(e)}]"
    
    @staticmethod
    def extract_text_from_docx(file_path: str) -> str:
        """从Word文档提取内容"""
        if not DOCX_AVAILABLE:
            return "[Word文档处理功能需要安装python-docx库]"
        
        try:
            doc = Document(file_path)
            return "\n".join([paragraph.text for paragraph in doc.paragraphs])
        except Exception as e:
            return f"[Word文档处理错误: {str(e)}]"
    
    @staticmethod
    def extract_text_from_md(file_path: str) -> str:
        """从Markdown文件提取内容"""
        return DocumentProcessor.extract_text_from_txt(file_path)
    
    @staticmethod
    def extract_text(file_path: str, file_type: str) -> str:
        """根据文件类型提取文本内容"""
        file_type = file_type.lower()
        
        if file_type in ['txt', 'text']:
            return DocumentProcessor.extract_text_from_txt(file_path)
        elif file_type == 'pdf':
            return DocumentProcessor.extract_text_from_pdf(file_path)
        elif file_type in ['docx', 'doc']:
            return DocumentProcessor.extract_text_from_docx(file_path)
        elif file_type in ['md', 'markdown']:
            return DocumentProcessor.extract_text_from_md(file_path)
        else:
            return f"[不支持的文件格式: {file_type}]"

# 数据库管理类
class DatabaseManager:
    """数据库管理类"""
    
    def __init__(self, db_path: str):
        self.db_path = db_path
        self.init_database()
    
    def get_connection(self):
        """获取数据库连接"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row  # 使查询结果可以像字典一样访问
        return conn
    
    def init_database(self):
        """初始化数据库表"""
        with self.get_connection() as conn:
            # 文档表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    content TEXT,
                    file_path TEXT,
                    file_type TEXT,
                    file_size INTEGER,
                    hash_value TEXT UNIQUE,
                    tags TEXT,  -- JSON格式存储标签
                    metadata TEXT,  -- JSON格式存储元数据
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_deleted BOOLEAN DEFAULT 0
                )
            ''')
            
            # 知识节点表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_nodes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    node_type TEXT NOT NULL,  -- concept, person, location, etc.
                    description TEXT,
                    properties TEXT,  -- JSON格式存储属性
                    frequency INTEGER DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # 知识边表（关系）
            conn.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_edges (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_id INTEGER NOT NULL,
                    target_id INTEGER NOT NULL,
                    relation_type TEXT NOT NULL,
                    weight REAL DEFAULT 1.0,
                    properties TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES knowledge_nodes(id),
                    FOREIGN KEY (target_id) REFERENCES knowledge_nodes(id)
                )
            ''')
            
            # 用户行为表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_behaviors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    document_id INTEGER,
                    action_type TEXT NOT NULL,  -- view, edit, search, etc.
                    duration INTEGER,  -- 操作持续时间（秒）
                    details TEXT,  -- JSON格式存储详细信息
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES documents(id)
                )
            ''')

# AI处理类
class AIProcessor:
    """AI处理类 - 封装各种AI算法"""
    
    def __init__(self, model_name: str = None):
        self.model_name = model_name or Config.NLP_MODEL
        self.nlp = None
        self.vectorizer = TfidfVectorizer(max_features=1000, stop_words='english')
        self._load_model()
    
    def _load_model(self):
        """加载NLP模型"""
        try:
            self.nlp = spacy.load(self.model_name)
        except OSError:
            print(f"警告：无法加载模型 {self.model_name}，使用基础文本处理")
            # 这里可以添加备选方案
    
    def extract_keywords(self, text: str, max_keywords: int = 10) -> List[str]:
        """提取关键词"""
        if not text or text.startswith('['):  # 跳过错误信息
            return []
        
        if self.nlp:
            doc = self.nlp(text)
            # 提取名词和形容词作为关键词
            keywords = [token.text.lower() for token in doc 
                       if token.pos_ in ['NOUN', 'ADJ'] 
                       and len(token.text) > 2 
                       and not token.is_stop]
            
            # 计算TF-IDF得到最重要的关键词
            if keywords:
                keyword_freq = {}
                for kw in keywords:
                    keyword_freq[kw] = keyword_freq.get(kw, 0) + 1
                
                # 返回频率最高的关键词
                sorted_keywords = sorted(keyword_freq.items(), 
                                       key=lambda x: x[1], reverse=True)
                return [kw[0] for kw in sorted_keywords[:max_keywords]]
        
        # 备选方案：简单的词频统计
        words = text.lower().split()
        word_freq = {}
        for word in words:
            if len(word) > 2:
                word_freq[word] = word_freq.get(word, 0) + 1
        
        sorted_words = sorted(word_freq.items(), key=lambda x: x[1], reverse=True)
        return [word[0] for word in sorted_words[:max_keywords]]
    
    def calculate_similarity(self, text1: str, text2: str) -> float:
        """计算文本相似度"""
        try:
            # 使用TF-IDF和余弦相似度
            tfidf_matrix = self.vectorizer.fit_transform([text1, text2])
            similarity = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            return float(similarity)
        except:
            # 备选方案：简单的词重叠率
            words1 = set(text1.lower().split())
            words2 = set(text2.lower().split())
            intersection = words1.intersection(words2)
            union = words1.union(words2)
            return len(intersection) / len(union) if union else 0.0
    
    def extract_entities(self, text: str) -> Dict[str, List[str]]:
        """提取命名实体"""
        entities = {
            'persons': [],
            'locations': [],
            'organizations': [],
            'concepts': []
        }
        
        if self.nlp and not text.startswith('['):
            doc = self.nlp(text)
            for ent in doc.ents:
                if ent.label_ == 'PERSON':
                    entities['persons'].append(ent.text)
                elif ent.label_ in ['GPE', 'LOC']:
                    entities['locations'].append(ent.text)
                elif ent.label_ == 'ORG':
                    entities['organizations'].append(ent.text)
                else:
                    entities['concepts'].append(ent.text)
        
        return entities

# 知识图谱管理类
class KnowledgeGraphManager:
    """知识图谱管理类"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.graph = nx.DiGraph()
        self._load_graph_from_db()
    
    def _load_graph_from_db(self):
        """从数据库加载知识图谱"""
        try:
            with self.db.get_connection() as conn:
                # 加载节点
                nodes = conn.execute('SELECT * FROM knowledge_nodes').fetchall()
                for node in nodes:
                    self.graph.add_node(node['id'], 
                                      name=node['name'], 
                                      node_type=node['node_type'],
                                      description=node['description'])
                
                # 加载边
                edges = conn.execute('SELECT * FROM knowledge_edges').fetchall()
                for edge in edges:
                    self.graph.add_edge(edge['source_id'], edge['target_id'],
                                      relation_type=edge['relation_type'],
                                      weight=edge['weight'])
        except Exception as e:
            print(f"加载知识图谱时出错: {e}")
    
    def add_knowledge_node(self, name: str, node_type: str, description: str = None) -> int:
        """添加知识节点"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    'INSERT INTO knowledge_nodes (name, node_type, description) VALUES (?, ?, ?)',
                    (name, node_type, description)
                )
                node_id = cursor.lastrowid
                self.graph.add_node(node_id, name=name, node_type=node_type, description=description)
                return node_id
        except Exception as e:
            print(f"添加知识节点时出错: {e}")
            return -1
    
    def add_knowledge_edge(self, source_id: int, target_id: int, 
                          relation_type: str, weight: float = 1.0) -> int:
        """添加知识边（关系）"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    'INSERT INTO knowledge_edges (source_id, target_id, relation_type, weight) VALUES (?, ?, ?, ?)',
                    (source_id, target_id, relation_type, weight)
                )
                edge_id = cursor.lastrowid
                self.graph.add_edge(source_id, target_id, relation_type=relation_type, weight=weight)
                return edge_id
        except Exception as e:
            print(f"添加知识边时出错: {e}")
            return -1
    
    def get_graph_data(self) -> Dict:
        """获取图谱数据用于可视化"""
        nodes = []
        edges = []
        
        # 从数据库获取节点信息（包括频率）
        with self.db.get_connection() as conn:
            db_nodes = conn.execute('SELECT * FROM knowledge_nodes').fetchall()
            node_freq_map = {node['id']: node['frequency'] for node in db_nodes}
        
        # 转换节点格式
        for node_id, node_data in self.graph.nodes(data=True):
            nodes.append({
                'id': node_id,
                'name': node_data.get('name', f'Node {node_id}'),
                'type': node_data.get('node_type', 'unknown'),
                'description': node_data.get('description', ''),
                'frequency': node_freq_map.get(node_id, 1)
            })
        
        # 转换边格式
        for source, target, edge_data in self.graph.edges(data=True):
            edges.append({
                'source': source,
                'target': target,
                'type': edge_data.get('relation_type', 'related'),
                'weight': edge_data.get('weight', 1.0)
            })
        
        return {'nodes': nodes, 'edges': edges}

# 文档管理类
class DocumentManager:
    """文档管理类"""
    
    def __init__(self, db_manager: DatabaseManager, ai_processor: AIProcessor):
        self.db = db_manager
        self.ai = ai_processor
        self.doc_processor = DocumentProcessor()
    
    def calculate_file_hash(self, file_path: str) -> str:
        """计算文件哈希值"""
        hash_md5 = hashlib.md5()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                hash_md5.update(chunk)
        return hash_md5.hexdigest()
    
    def process_document(self, file_path: str, title: str = None) -> Dict[str, Any]:
        """处理文档，提取信息和知识"""
        try:
            file_type = os.path.splitext(file_path)[1][1:].lower()
            
            # 提取文档内容
            content = self.doc_processor.extract_text(file_path, file_type)
            
            # 提取关键词
            keywords = self.ai.extract_keywords(content)
            
            # 提取实体
            entities = self.ai.extract_entities(content)
            
            # 计算文档哈希
            file_hash = self.calculate_file_hash(file_path)
            
            # 准备文档数据
            doc_data = {
                'title': title or os.path.basename(file_path),
                'content': content[:2000] if not content.startswith('[') else content,  # 存储前2000字符作为摘要
                'file_path': file_path,
                'file_type': file_type,
                'file_size': os.path.getsize(file_path),
                'hash_value': file_hash,
                'keywords': keywords,
                'entities': entities,
                'metadata': {
                    'word_count': len(content.split()) if not content.startswith('[') else 0,
                    'char_count': len(content),
                    'processing_time': datetime.now().isoformat(),
                    'processing_status': 'success' if not content.startswith('[') else 'warning',
                    'processing_message': content if content.startswith('[') else '处理成功'
                }
            }
            
            return doc_data
            
        except Exception as e:
            print(f"处理文档 {file_path} 时出错: {e}")
            return {
                'title': title or os.path.basename(file_path),
                'content': f"[处理错误: {str(e)}]",
                'file_path': file_path,
                'file_type': os.path.splitext(file_path)[1][1:].lower(),
                'file_size': os.path.getsize(file_path),
                'hash_value': self.calculate_file_hash(file_path),
                'keywords': [],
                'entities': {'persons': [], 'locations': [], 'organizations': [], 'concepts': []},
                'metadata': {
                    'processing_status': 'error',
                    'processing_message': str(e),
                    'processing_time': datetime.now().isoformat()
                }
            }
    
    def save_document(self, doc_data: Dict[str, Any]) -> Optional[int]:
        """保存文档到数据库"""
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute('''
                    INSERT INTO documents 
                    (title, content, file_path, file_type, file_size, hash_value, tags, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    doc_data['title'],
                    doc_data['content'],
                    doc_data['file_path'],
                    doc_data['file_type'],
                    doc_data['file_size'],
                    doc_data['hash_value'],
                    json.dumps(doc_data['keywords'], ensure_ascii=False),
                    json.dumps(doc_data['metadata'], ensure_ascii=False)
                ))
                return cursor.lastrowid
        except sqlite3.IntegrityError:
            print(f"文档 {doc_data['title']} 已存在（哈希值重复）")
            return None
        except Exception as e:
            print(f"保存文档时出错: {e}")
            return None
    
    def search_documents(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """搜索文档 - 精准搜索版本，只返回真正相关的文档"""
        with self.db.get_connection() as conn:
            query_lower = query.lower().strip()
            if not query_lower:
                return []
            
            # 判断搜索词类型：文件名搜索（短词、包含点号、或纯字母数字）还是内容搜索
            is_filename_search = (
                len(query_lower) <= 20 and  # 短词更可能是文件名
                ('.' in query_lower or  # 包含扩展名
                 query_lower.replace('_', '').replace('-', '').replace('.', '').isalnum())  # 纯字母数字
            )
            
            # 获取所有未删除的文档
            all_docs = conn.execute('''
                SELECT * FROM documents 
                WHERE is_deleted = 0
            ''').fetchall()
            
            # 计算相关性分数
            scored_docs = []
            for doc in all_docs:
                doc_dict = dict(doc)
                score = 0.0
                title = doc_dict.get('title', '').lower()
                content = doc_dict.get('content', '').lower()
                file_path = doc_dict.get('file_path', '')
                filename = os.path.basename(file_path).lower() if file_path else ''
                
                # 优先匹配文件名和标题
                # 1. 文件名完全匹配 - 最高优先级
                if filename == query_lower:
                    score += 100.0
                # 2. 文件名开头匹配（去掉扩展名）
                elif filename.startswith(query_lower):
                    score += 80.0
                # 3. 文件名包含（作为完整词）
                elif query_lower in filename:
                    # 检查是否是完整词匹配（前后是分隔符）
                    pattern = r'\b' + re.escape(query_lower) + r'\b'
                    if re.search(pattern, filename):
                        score += 60.0
                    else:
                        score += 40.0
                
                # 4. 标题完全匹配
                if title == query_lower:
                    score += 90.0
                # 5. 标题开头匹配
                elif title.startswith(query_lower):
                    score += 70.0
                # 6. 标题包含（作为完整词）
                elif query_lower in title:
                    pattern = r'\b' + re.escape(query_lower) + r'\b'
                    if re.search(pattern, title):
                        score += 50.0
                    else:
                        score += 30.0
                
                # 如果是文件名搜索，只匹配文件名和标题，不匹配内容
                if is_filename_search:
                    # 文件名搜索模式下，内容匹配权重极低
                    if query_lower in content and score == 0:
                        # 只有在完全没有文件名/标题匹配时，才考虑内容
                        # 但即使这样，也只给很低的分数
                        count = content.count(query_lower)
                        if count >= 3:  # 至少出现3次才考虑
                            score += min(count * 0.5, 5.0)  # 最多5分
                else:
                    # 内容搜索模式：内容匹配
                    if query_lower in content:
                        # 计算出现次数，但要求至少出现2次
                        count = content.count(query_lower)
                        if count >= 2:
                            score += min(count * 1.5, 25.0)  # 最多25分
                    
                    # 关键词匹配（从tags中）
                    tags_str = doc_dict.get('tags', '')
                    if tags_str:
                        try:
                            tags = json.loads(tags_str)
                            if isinstance(tags, list):
                                for tag in tags:
                                    if query_lower in tag.lower():
                                        score += 15.0
                        except:
                            pass
                    
                    # 使用TF-IDF计算相似度（如果内容足够长且不是错误信息）
                    if len(content) > 100 and not content.startswith('[') and not content.startswith('处理错误'):
                        try:
                            similarity = self.ai.calculate_similarity(query, content[:2000])
                            # 只有相似度较高时才加分
                            if similarity > 0.3:
                                score += similarity * 10.0  # 最多10分
                        except:
                            pass
                
                # 只添加有意义的匹配结果
                # 文件名搜索：至少要有文件名或标题匹配
                # 内容搜索：至少要有一定分数
                min_score = 25.0 if is_filename_search else 15.0
                
                if score >= min_score:
                    doc_dict['_search_score'] = score
                    scored_docs.append(doc_dict)
            
            # 按分数降序排序，然后按创建时间降序
            def get_timestamp(doc):
                try:
                    created_at = doc.get('created_at', '2000-01-01')
                    if isinstance(created_at, str):
                        try:
                            if ' ' in created_at:
                                dt = datetime.strptime(created_at.split('.')[0], '%Y-%m-%d %H:%M:%S')
                            else:
                                dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                            return dt.timestamp()
                        except:
                            return 0.0
                    return 0.0
                except:
                    return 0.0
            
            scored_docs.sort(key=lambda x: (x.get('_search_score', 0), get_timestamp(x)), reverse=True)
            
            # 移除临时分数字段
            for doc in scored_docs:
                doc.pop('_search_score', None)
            
            return scored_docs[:limit]

# Flask应用创建函数
def create_app():
    """创建Flask应用"""
    app = Flask(__name__)
    app.config.from_object(Config)
    app.config['JSON_AS_ASCII'] = False
    Config.init_app(app)
    
    # 启用CORS
    CORS(app)
    
    # 初始化各个管理器
    db_manager = DatabaseManager(Config.DATABASE_PATH)
    ai_processor = AIProcessor()
    kg_manager = KnowledgeGraphManager(db_manager)
    doc_manager = DocumentManager(db_manager, ai_processor)
    
    # 注册路由
    @app.route('/')
    def index():
        """主页"""
        return render_template('index.html')
        
    @app.route('/static/<path:filename>')
    def serve_static(filename):
        return send_from_directory('static', filename)
    
    @app.route('/api/documents', methods=['GET', 'POST'])
    def handle_documents():
        """文档管理API"""
        if request.method == 'GET':
            # 获取文档列表
            limit = request.args.get('limit', 20, type=int)
            offset = request.args.get('offset', 0, type=int)
            
            with db_manager.get_connection() as conn:
                documents = conn.execute(
                    'SELECT * FROM documents WHERE is_deleted = 0 ORDER BY created_at DESC LIMIT ? OFFSET ?',
                    (limit, offset)
                ).fetchall()
                
                return jsonify({
                    'success': True,
                    'data': [dict(doc) for doc in documents],
                    'total': conn.execute('SELECT COUNT(*) FROM documents WHERE is_deleted = 0').fetchone()[0]
                })
        
        elif request.method == 'POST':
            # 上传文档
            if 'file' not in request.files:
                return jsonify({'success': False, 'message': '没有上传文件'}), 400
            
            file = request.files['file']
            if file.filename == '':
                return jsonify({'success': False, 'message': '没有选择文件'}), 400
            
            if file:
                # 检查文件类型
                filename = file.filename
                file_ext = os.path.splitext(filename)[1][1:].lower()
                allowed_types = ['txt', 'md', 'pdf', 'docx', 'doc']
                
                if file_ext not in allowed_types:
                    return jsonify({
                        'success': False, 
                        'message': f'不支持的文件格式: {file_ext}. 支持的格式: {", ".join(allowed_types)}'
                    }), 400
                
                # 保存文件
                file_path = os.path.join(Config.UPLOAD_FOLDER, filename)
                file.save(file_path)
                
                # 处理文档
                doc_data = doc_manager.process_document(file_path, filename)
                if doc_data:
                    doc_id = doc_manager.save_document(doc_data)
                    if doc_id:
                        # 如果处理成功，从关键词创建知识节点
                        if doc_data['keywords'] and not doc_data['content'].startswith('['):
                            try:
                                for keyword in doc_data['keywords'][:5]:  # 限制前5个关键词
                                    kg_manager.add_knowledge_node(keyword, 'concept', f'从文档"{doc_data["title"]}"提取的关键词')
                            except Exception as e:
                                print(f"创建知识节点时出错: {e}")
                        
                        return jsonify({
                            'success': True,
                            'message': '文档上传成功',
                            'document_id': doc_id,
                            'processing_status': doc_data['metadata']['processing_status'],
                            'processing_message': doc_data['metadata']['processing_message']
                        })
                
                return jsonify({'success': False, 'message': '文档处理失败'}), 500
    
    @app.route('/api/search')
    def search():
        """搜索API"""
        query = request.args.get('q', '')
        if not query:
            return jsonify({'success': False, 'message': '搜索关键词不能为空'}), 400
        
        results = doc_manager.search_documents(query)
        return jsonify({
            'success': True,
            'data': results,
            'query': query,
            'count': len(results)
        })
    
    @app.route('/api/knowledge-graph')
    def get_knowledge_graph():
        """获取知识图谱数据"""
        graph_data = kg_manager.get_graph_data()
        return jsonify({
            'success': True,
            'data': graph_data,
            'node_count': len(graph_data['nodes']),
            'edge_count': len(graph_data['edges'])
        })
    
    @app.route('/knowledge-graph')
    def knowledge_graph_page():
        """知识图谱可视化页面"""
        return render_template('knowledge_graph.html')

    @app.route('/api/knowledge-graph/search')
    def search_knowledge_graph():
        """搜索知识图谱"""
        query = request.args.get('q', '')
        if not query:
            return jsonify({'success': False, 'message': '搜索关键词不能为空'}), 400
    
        try:
            # 获取完整的图谱数据
            graph_data = kg_manager.get_graph_data()
        
            # 过滤包含搜索词的节点（不区分大小写）
            filtered_nodes = [
                node for node in graph_data['nodes'] 
                if query.lower() in node['name'].lower() or 
                (node.get('description') and query.lower() in node['description'].lower())
            ]
        
            # 获取过滤后节点的ID集合（统一转换为字符串）
            filtered_node_ids = {str(node['id']) for node in filtered_nodes}
            
            # 过滤相关的边（源节点或目标节点在过滤后的节点中）
            filtered_edges = [
                edge for edge in graph_data['edges'] 
                if str(edge['source']) in filtered_node_ids or str(edge['target']) in filtered_node_ids
            ]
        
            return jsonify({
                'success': True,
                'data': {
                    'nodes': filtered_nodes,
                    'edges': filtered_edges
                },
                'original_count': len(graph_data['nodes']),
                'filtered_count': len(filtered_nodes)
            })
        
        except Exception as e:
            return jsonify({
                'success': False, 
                'message': f'搜索出错: {str(e)}'
            }), 500
    
    @app.route('/api/recommendations/<int:user_id>', defaults={'user_id': 1})
    @app.route('/api/recommendations/<int:user_id>')
    def get_recommendations(user_id):
        """获取个性化推荐"""
        # 简化处理：基于用户最近的文档推荐相似的文档
        # 实际应用中需要更复杂的推荐算法
        
        with db_manager.get_connection() as conn:
            # 获取用户最近的文档
            recent_docs = conn.execute('''
                SELECT * FROM documents 
                WHERE id IN (
                    SELECT document_id FROM user_behaviors 
                    WHERE user_id = ? ORDER BY timestamp DESC LIMIT 5
                )
            ''', (str(user_id),)).fetchall()
            
            if not recent_docs:
                # 如果没有用户行为，推荐最新的文档
                recent_docs = conn.execute(
                    'SELECT * FROM documents WHERE is_deleted = 0 ORDER BY created_at DESC LIMIT 5'
                ).fetchall()
            
            # 基于关键词推荐相似文档
            recommendations = []
            for doc in recent_docs:
                if doc['tags']:
                    try:
                        tags = json.loads(doc['tags'])
                        for tag in tags[:3]:  # 使用前3个标签
                            similar_docs = conn.execute('''
                                SELECT * FROM documents 
                                WHERE tags LIKE ? AND id != ? AND is_deleted = 0
                                ORDER BY created_at DESC LIMIT 3
                            ''', (f'%{tag}%', doc['id'])).fetchall()
                            
                            for similar_doc in similar_docs:
                                recommendations.append({
                                    'source_document': dict(doc),
                                    'recommended_document': dict(similar_doc),
                                    'reason': f'基于关键词 "{tag}" 推荐',
                                    'score': 0.8  # 简化的相似度评分
                                })
                    except:
                        continue
            
            return jsonify({
                'success': True,
                'data': recommendations[:10],  # 限制推荐数量
                'based_on_documents': len(recent_docs)
            })
    
    @app.route('/api/system-info')
    def system_info():
        """获取系统信息"""
        return jsonify({
            'success': True,
            'data': {
                'name': '智能个人知识管理系统',
                'version': '1.0.0',
                'python_version': sys.version,
                'spacy_model': Config.NLP_MODEL,
                'pdf_support': PDF_AVAILABLE,
                'docx_support': DOCX_AVAILABLE,
                'upload_folder': Config.UPLOAD_FOLDER,
                'database_path': Config.DATABASE_PATH
            }
        })
    
    @app.route('/api/analytics/study-time')
    def get_study_time():
        """获取学习时长统计"""
        period = request.args.get('period', 'week')
        
        # 根据时间段生成模拟数据（实际应用中应从数据库查询）
        if period == 'week':
            labels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
            # 基于文档创建时间生成学习时长
            with db_manager.get_connection() as conn:
                docs = conn.execute(
                    'SELECT created_at FROM documents WHERE is_deleted = 0 ORDER BY created_at DESC LIMIT 7'
                ).fetchall()
                values = []
                for i in range(7):
                    if i < len(docs):
                        # 根据文档数量估算学习时长（小时）
                        values.append(round(0.5 + (len(docs) - i) * 0.3, 1))
                    else:
                        values.append(round(0.5 + (7 - i) * 0.2, 1))
        elif period == 'month':
            labels = [f'第{i}周' for i in range(1, 5)]
            with db_manager.get_connection() as conn:
                total_docs = conn.execute('SELECT COUNT(*) FROM documents WHERE is_deleted = 0').fetchone()[0]
                avg_per_week = total_docs / 4 if total_docs > 0 else 1
                values = [round(avg_per_week * 0.5 + i * 0.3, 1) for i in range(4)]
        else:  # quarter
            labels = ['第1月', '第2月', '第3月']
            with db_manager.get_connection() as conn:
                total_docs = conn.execute('SELECT COUNT(*) FROM documents WHERE is_deleted = 0').fetchone()[0]
                avg_per_month = total_docs / 3 if total_docs > 0 else 1
                values = [round(avg_per_month * 0.8 + i * 0.5, 1) for i in range(3)]
        
        return jsonify({
            'success': True,
            'data': {
                'labels': labels,
                'values': values,
                'period': period
            }
        })
    
    @app.route('/api/analytics/knowledge-level')
    def get_knowledge_level():
        """获取知识点掌握分布"""
        with db_manager.get_connection() as conn:
            total_nodes = conn.execute('SELECT COUNT(*) FROM knowledge_nodes').fetchone()[0]
            
            # 简化的掌握度计算（实际应用中需要更复杂的算法）
            if total_nodes == 0:
                levels = [
                    {'value': 0, 'name': '已掌握'},
                    {'value': 0, 'name': '学习中'},
                    {'value': 0, 'name': '待学习'}
                ]
            else:
                mastered = int(total_nodes * 0.35)
                learning = int(total_nodes * 0.45)
                pending = total_nodes - mastered - learning
                levels = [
                    {'value': mastered, 'name': '已掌握'},
                    {'value': learning, 'name': '学习中'},
                    {'value': pending, 'name': '待学习'}
                ]
        
        return jsonify({
            'success': True,
            'data': {
                'levels': levels,
                'total': total_nodes
            }
        })
    
    @app.route('/api/analytics/prediction')
    def get_prediction():
        """获取学习进展预测"""
        with db_manager.get_connection() as conn:
            total_docs = conn.execute('SELECT COUNT(*) FROM documents WHERE is_deleted = 0').fetchone()[0]
            total_nodes = conn.execute('SELECT COUNT(*) FROM knowledge_nodes').fetchone()[0]
            
            # 简化的预测算法
            # 假设目标：100个文档，200个知识点
            target_docs = 100
            target_nodes = 200
            
            doc_progress = min(100, int((total_docs / target_docs) * 100)) if target_docs > 0 else 0
            node_progress = min(100, int((total_nodes / target_nodes) * 100)) if target_nodes > 0 else 0
            overall_progress = int((doc_progress + node_progress) / 2)
            
            # 计算预测完成时间（基于当前进度和学习速度）
            if overall_progress > 0:
                remaining_progress = 100 - overall_progress
                # 假设每天进步2%
                estimated_days = remaining_progress / 2
                estimated_weeks = round(estimated_days / 7, 1)
                estimated_time = f'{estimated_weeks}周'
            else:
                estimated_time = '4周'
            
            # 生成建议
            recommendations = []
            if total_docs < 10:
                recommendations.append('增加文档上传频次，建立知识库基础')
            if total_nodes < 20:
                recommendations.append('系统会自动从文档中提取关键词，建议上传更多相关文档')
            if total_docs > 0 and total_nodes > 0:
                recommendations.append('建立更多知识点之间的关联，完善知识网络')
            if not recommendations:
                recommendations = [
                    '保持当前学习节奏',
                    '定期复习已学知识点',
                    '探索新的知识领域'
                ]
        
        return jsonify({
            'success': True,
            'data': {
                'progress': overall_progress,
                'estimated_time': estimated_time,
                'recommended_time': '2小时/天',
                'recommendations': recommendations[:3]  # 最多3条建议
            }
        })
    
    @app.route('/api/documents/<int:doc_id>')
    def get_document_detail(doc_id):
        """获取文档详情"""
        with db_manager.get_connection() as conn:
            doc = conn.execute(
                'SELECT * FROM documents WHERE id = ? AND is_deleted = 0',
                (doc_id,)
            ).fetchone()
            
            if not doc:
                return jsonify({'success': False, 'message': '文档不存在'}), 404
            
            # 读取完整内容
            try:
                full_content = doc_manager.doc_processor.extract_text(doc['file_path'], doc['file_type'])
            except:
                full_content = doc['content']
            
            doc_dict = dict(doc)
            doc_dict['full_content'] = full_content
            
            # 解析JSON字段
            if doc_dict.get('tags'):
                try:
                    doc_dict['tags'] = json.loads(doc_dict['tags'])
                except:
                    doc_dict['tags'] = []
            
            if doc_dict.get('metadata'):
                try:
                    doc_dict['metadata'] = json.loads(doc_dict['metadata'])
                except:
                    doc_dict['metadata'] = {}
            
            return jsonify({
                'success': True,
                'data': doc_dict
            })
    
    @app.route('/api/documents/<int:doc_id>', methods=['DELETE'])
    def delete_document(doc_id):
        """删除文档（软删除）"""
        try:
            with db_manager.get_connection() as conn:
                conn.execute(
                    'UPDATE documents SET is_deleted = 1 WHERE id = ?',
                    (doc_id,)
                )
            return jsonify({
                'success': True,
                'message': '文档已删除'
            })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'删除失败: {str(e)}'
            }), 500
    
    return app

# 主程序入口
if __name__ == '__main__':
    app = create_app()
    
    # 开发模式下运行
    print("=" * 60)
    print("智能个人知识管理系统 - 修复版本")
    print("=" * 60)
    print(f"数据库路径: {Config.DATABASE_PATH}")
    print(f"上传目录: {Config.UPLOAD_FOLDER}")
    print(f"PDF支持: {'✓' if PDF_AVAILABLE else '✗'}")
    print(f"Word文档支持: {'✓' if DOCX_AVAILABLE else '✗'}")
    print("=" * 60)
    print("支持的文件格式: .txt, .md, .pdf, .docx, .doc")
    print("访问地址: http://localhost:5000")
    print("=" * 60)
    
    app.run(debug=True, host='0.0.0.0', port=5000)