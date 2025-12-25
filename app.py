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
from typing import Dict, List, Optional, Any, Tuple
import hashlib
import mimetypes

# 第三方库导入
from flask import Flask, request, jsonify, render_template, send_file, send_from_directory, session, redirect, url_for
from flask_cors import CORS
from functools import wraps
import spacy
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import networkx as nx
import requests
import hashlib as hash_lib

# 导入配置文件
try:
    from config import ALIYUN_API_KEY
except ImportError:
    ALIYUN_API_KEY = None
    print("警告：未找到 config.py 文件，AI 学习助手功能将不可用")

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

# 尝试导入textract库（支持多种格式，包括.doc）
try:
    import textract
    TEXTTRACT_AVAILABLE = True
except ImportError:
    TEXTTRACT_AVAILABLE = False
    print("提示：未安装textract库，.doc格式文档处理功能将受限")

# 尝试导入win32com（Windows系统支持.doc格式）
try:
    import win32com.client
    WIN32COM_AVAILABLE = True
except ImportError:
    WIN32COM_AVAILABLE = False

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
        """从Word文档(.docx)提取内容"""
        if not DOCX_AVAILABLE:
            return "[Word文档处理功能需要安装python-docx库]"
        
        try:
            doc = Document(file_path)
            return "\n".join([paragraph.text for paragraph in doc.paragraphs])
        except Exception as e:
            return f"[Word文档处理错误: {str(e)}]"
    
    @staticmethod
    def extract_text_from_doc(file_path: str) -> str:
        """从Word文档(.doc)提取内容（旧格式）"""
        # 方法1: 尝试使用textract
        if TEXTTRACT_AVAILABLE:
            try:
                text = textract.process(file_path).decode('utf-8')
                if text and text.strip():
                    return text
            except Exception as e:
                print(f"textract处理失败: {e}")
        
        # 方法2: 尝试使用win32com (Windows)
        if WIN32COM_AVAILABLE:
            try:
                word = win32com.client.Dispatch("Word.Application")
                word.Visible = False
                # 转换为绝对路径
                abs_path = os.path.abspath(file_path)
                doc = word.Documents.Open(abs_path)
                text = doc.Content.Text
                doc.Close(False)  # False表示不保存
                word.Quit()
                if text and text.strip():
                    return text
            except Exception as e:
                print(f"win32com处理失败: {e}")
                try:
                    # 确保Word应用被关闭
                    word.Quit()
                except:
                    pass
        
        # 如果都不可用，返回友好的提示信息
        return "[.doc格式文档需要特殊处理库。\n\n解决方案：\n1. 安装textract库: pip install textract\n2. 或在Windows系统上安装pywin32: pip install pywin32\n3. 或将文档转换为.docx格式后重新上传\n\n注意：.doc是旧版Word格式，python-docx库无法处理。]"
    
    @staticmethod
    def extract_text_from_md(file_path: str) -> str:
        """从Markdown文件提取内容"""
        return DocumentProcessor.extract_text_from_txt(file_path)
    
    @staticmethod
    def extract_text_from_ppt(file_path: str) -> str:
        """从PPT文件提取内容（暂不支持文本提取）"""
        return "[PPT文件暂不支持文本提取，仅支持上传和下载]"
    
    @staticmethod
    def extract_text(file_path: str, file_type: str = None) -> str:
        """根据文件类型提取文本内容"""
        # 如果未提供file_type，从文件路径自动判断
        if not file_type:
            file_type = os.path.splitext(file_path)[1][1:].lower()
        else:
            file_type = file_type.lower()
        
        # 确保文件存在
        if not os.path.exists(file_path):
            return f"[文件不存在: {file_path}]"
        
        if file_type in ['txt', 'text']:
            return DocumentProcessor.extract_text_from_txt(file_path)
        elif file_type == 'pdf':
            return DocumentProcessor.extract_text_from_pdf(file_path)
        elif file_type == 'docx':
            return DocumentProcessor.extract_text_from_docx(file_path)
        elif file_type == 'doc':
            return DocumentProcessor.extract_text_from_doc(file_path)
        elif file_type in ['md', 'markdown']:
            return DocumentProcessor.extract_text_from_md(file_path)
        elif file_type in ['ppt', 'pptx']:
            return DocumentProcessor.extract_text_from_ppt(file_path)
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
                    document_id INTEGER,  -- 关联的文档ID，确保节点来自已上传的文件
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (document_id) REFERENCES documents(id)
                )
            ''')
            
            # 如果表已存在但没有document_id字段，添加该字段
            try:
                conn.execute('ALTER TABLE knowledge_nodes ADD COLUMN document_id INTEGER')
            except sqlite3.OperationalError:
                # 字段已存在，忽略错误
                pass
            
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
            
            # 用户表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    last_login TIMESTAMP
                )
            ''')
            
            # 用户行为表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS user_behaviors (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    document_id INTEGER,
                    action_type TEXT NOT NULL,  -- view, edit, search, etc.
                    duration INTEGER,  -- 操作持续时间（秒）
                    details TEXT,  -- JSON格式存储详细信息
                    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users(id),
                    FOREIGN KEY (document_id) REFERENCES documents(id)
                )
            ''')
            
            # 知识图谱方案表
            conn.execute('''
                CREATE TABLE IF NOT EXISTS knowledge_graph_schemes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    is_default BOOLEAN DEFAULT 0
                )
            ''')
            
            # 为知识节点表添加scheme_id字段
            try:
                conn.execute('ALTER TABLE knowledge_nodes ADD COLUMN scheme_id INTEGER')
            except sqlite3.OperationalError:
                # 字段已存在，忽略错误
                pass
            
            # 为知识边表添加scheme_id字段
            try:
                conn.execute('ALTER TABLE knowledge_edges ADD COLUMN scheme_id INTEGER')
            except sqlite3.OperationalError:
                # 字段已存在，忽略错误
                pass
            
            # 创建默认方案（如果不存在）
            default_scheme = conn.execute('SELECT id FROM knowledge_graph_schemes WHERE is_default = 1').fetchone()
            if not default_scheme:
                conn.execute('''
                    INSERT INTO knowledge_graph_schemes (name, description, is_default)
                    VALUES ('默认方案', '系统默认的知识图谱方案', 1)
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

# AI学习助手类
class AIAssistant:
    """AI学习助手类 - 使用DeepSeek API提供智能问答和学习建议"""
    
    def __init__(self, api_key: str = None):
        self.api_key = api_key or ALIYUN_API_KEY
        self.api_url = "https://api.deepseek.com/v1/chat/completions"
        self.model = "deepseek-chat"
        
    def _call_api(self, messages: List[Dict[str, str]], temperature: float = 0.7) -> Optional[str]:
        """调用DeepSeek API"""
        if not self.api_key:
            return None
        
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}"
            }
            
            data = {
                "model": self.model,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": 2000
            }
            
            response = requests.post(
                self.api_url,
                headers=headers,
                json=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                if 'choices' in result and len(result['choices']) > 0:
                    return result['choices'][0]['message']['content']
            else:
                print(f"DeepSeek API 错误: {response.status_code} - {response.text}")
                return None
                
        except Exception as e:
            print(f"调用DeepSeek API失败: {str(e)}")
            return None
    
    def chat(self, user_message: str, context: List[Dict[str, str]] = None) -> Dict[str, Any]:
        """与AI助手对话"""
        system_prompt = """你是一个专业的学习助手，专门帮助学生进行知识管理和学习。
你的职责包括：
1. 回答学生关于学习内容的问题
2. 提供学习建议和学习路径规划
3. 解释复杂的概念和知识点
4. 帮助学生理解知识之间的关联
5. 提供复习建议和记忆技巧

请用中文回答，回答要简洁明了、专业准确。"""
        
        messages = [{"role": "system", "content": system_prompt}]
        
        # 添加上下文对话历史
        if context:
            messages.extend(context)
        
        # 添加当前用户消息
        messages.append({"role": "user", "content": user_message})
        
        response = self._call_api(messages)
        
        if response:
            return {
                "success": True,
                "message": response,
                "model": self.model
            }
        else:
            return {
                "success": False,
                "message": "抱歉，AI服务暂时不可用，请稍后再试。",
                "error": "API调用失败"
            }
    
    def get_learning_suggestion(self, topic: str, user_documents: List[Dict] = None) -> Dict[str, Any]:
        """获取学习建议"""
        context_info = ""
        if user_documents:
            doc_titles = [doc.get('title', '') for doc in user_documents[:5]]
            context_info = f"\n用户已学习的文档包括：{', '.join(doc_titles)}"
        
        prompt = f"""请为以下学习主题提供详细的学习建议和学习路径：
主题：{topic}
{context_info}

请提供：
1. 学习路径规划（从基础到高级）
2. 重点知识点
3. 推荐的学习资源类型
4. 学习时间安排建议
5. 实践建议"""
        
        return self.chat(prompt)
    
    def explain_concept(self, concept: str, related_docs: List[Dict] = None) -> Dict[str, Any]:
        """解释概念"""
        context_info = ""
        if related_docs:
            doc_content = related_docs[0].get('content', '')[:500] if related_docs else ""
            context_info = f"\n相关文档内容片段：{doc_content}"
        
        prompt = f"""请详细解释以下概念：
概念：{concept}
{context_info}

请用通俗易懂的方式解释，包括：
1. 基本定义
2. 核心要点
3. 实际应用
4. 与其他概念的关系"""
        
        return self.chat(prompt)
    
    def generate_review_plan(self, knowledge_points: List[str]) -> Dict[str, Any]:
        """生成复习计划"""
        points_str = "\n".join([f"- {point}" for point in knowledge_points])
        
        prompt = f"""根据以下知识点，制定一个合理的复习计划：
{points_str}

请提供：
1. 复习时间安排（基于艾宾浩斯遗忘曲线）
2. 每个知识点的复习重点
3. 复习方法建议
4. 自测题目建议"""
        
        return self.chat(prompt)

# 知识图谱管理类
class KnowledgeGraphManager:
    """知识图谱管理类"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db = db_manager
        self.graph = nx.DiGraph()
        self.current_scheme_id = None
        self._load_default_scheme()
        self._load_graph_from_db()
    
    def _load_default_scheme(self):
        """加载默认方案ID"""
        try:
            with self.db.get_connection() as conn:
                default_scheme = conn.execute(
                    'SELECT id FROM knowledge_graph_schemes WHERE is_default = 1 LIMIT 1'
                ).fetchone()
                if default_scheme:
                    self.current_scheme_id = default_scheme['id']
                else:
                    # 如果没有默认方案，获取第一个方案
                    first_scheme = conn.execute(
                        'SELECT id FROM knowledge_graph_schemes ORDER BY id LIMIT 1'
                    ).fetchone()
                    if first_scheme:
                        self.current_scheme_id = first_scheme['id']
        except Exception as e:
            print(f"加载默认方案时出错: {e}")
    
    def set_current_scheme(self, scheme_id: int):
        """设置当前方案"""
        self.current_scheme_id = scheme_id
        self._load_graph_from_db()
    
    def _load_graph_from_db(self, scheme_id: int = None):
        """从数据库加载知识图谱
        只加载来自未删除文档的节点和指定方案的节点
        """
        if scheme_id is None:
            scheme_id = self.current_scheme_id
        
        if scheme_id is None:
            return
        
        try:
            with self.db.get_connection() as conn:
                # 加载来自未删除文档的所有类型节点和当前方案的节点
                nodes = conn.execute('''
                    SELECT kn.* FROM knowledge_nodes kn
                    LEFT JOIN documents d ON kn.document_id = d.id
                    WHERE (kn.document_id IS NULL OR d.is_deleted = 0)
                    AND (kn.scheme_id = ? OR kn.scheme_id IS NULL)
                ''', (scheme_id,)).fetchall()
                
                self.graph.clear()
                
                for node in nodes:
                    # sqlite3.Row不支持.get()方法，使用try-except处理可能不存在的字段
                    try:
                        description = node['description']
                    except (KeyError, IndexError):
                        description = None
                    
                    try:
                        document_id = node['document_id']
                    except (KeyError, IndexError):
                        document_id = None
                    
                    self.graph.add_node(node['id'], 
                                      name=node['name'], 
                                      node_type=node['node_type'],
                                      description=description,
                                      document_id=document_id)

                # 获取有效的节点ID集合
                valid_node_ids = {node['id'] for node in nodes}
                
                # 只加载两个端点都在有效节点集合中的边，且属于当前方案
                all_edges = conn.execute('''
                    SELECT * FROM knowledge_edges 
                    WHERE (scheme_id = ? OR scheme_id IS NULL)
                ''', (scheme_id,)).fetchall()
                for edge in all_edges:
                    if edge['source_id'] in valid_node_ids and edge['target_id'] in valid_node_ids:
                        self.graph.add_edge(edge['source_id'], edge['target_id'],
                                          relation_type=edge['relation_type'],
                                          weight=edge['weight'])

        except Exception as e:
            print(f"加载知识图谱时出错: {e}")
            import traceback
            traceback.print_exc()
    
    def add_knowledge_node(self, name: str, node_type: str = 'concept', description: str = None, document_id: int = None, scheme_id: int = None) -> int:
        """添加知识节点（用户手动管理）"""
        if scheme_id is None:
            scheme_id = self.current_scheme_id
        
        if scheme_id is None:
            return -1
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    'INSERT INTO knowledge_nodes (name, node_type, description, document_id, scheme_id) VALUES (?, ?, ?, ?, ?)',
                    (name, node_type, description, document_id, scheme_id)
                )
                node_id = cursor.lastrowid

                # 内存图更新
                self.graph.add_node(
                    node_id,
                    name=name,
                    node_type=node_type,
                    description=description,
                    document_id=document_id,
                    frequency=1
                )
                return node_id
        except Exception as e:
            print(f"添加知识节点时出错: {e}")
            import traceback
            traceback.print_exc()
            return -1
    
    def add_knowledge_edge(self, source_id: int, target_id: int, 
                          relation_type: str, weight: float = 1.0, scheme_id: int = None) -> int:
        """添加知识边（关系）"""
        if scheme_id is None:
            scheme_id = self.current_scheme_id
        
        if scheme_id is None:
            return -1
        
        try:
            with self.db.get_connection() as conn:
                cursor = conn.execute(
                    'INSERT INTO knowledge_edges (source_id, target_id, relation_type, weight, scheme_id) VALUES (?, ?, ?, ?, ?)',
                    (source_id, target_id, relation_type, weight, scheme_id)
                )
                edge_id = cursor.lastrowid
                self.graph.add_edge(source_id, target_id, relation_type=relation_type, weight=weight)
                return edge_id
        except Exception as e:
            print(f"添加知识边时出错: {e}")
            return -1
    
    def get_graph_data(self, scheme_id: int = None) -> Dict:
        """获取图谱数据用于可视化
        返回来自已上传且未删除文件的所有类型节点
        确保每个节点名称只出现一次（去重）
        """
        if scheme_id is None:
            scheme_id = self.current_scheme_id
        
        if scheme_id is None:
            return {'nodes': [], 'edges': []}
        
        nodes = []
        edges = []
        
        # 从数据库获取节点信息，按名称去重（所有类型）
        with self.db.get_connection() as conn:
            # 使用GROUP BY确保每个节点名称只出现一次，合并频率
            db_nodes = conn.execute('''
                SELECT 
                    MIN(kn.id) as id,
                    kn.name,
                    kn.node_type,
                    MAX(kn.description) as description,
                    SUM(kn.frequency) as frequency,
                    MIN(kn.document_id) as document_id
                FROM knowledge_nodes kn
                LEFT JOIN documents d ON kn.document_id = d.id
                WHERE (kn.document_id IS NULL OR d.is_deleted = 0)
                AND (kn.scheme_id = ? OR kn.scheme_id IS NULL)
                GROUP BY kn.name, kn.node_type
            ''', (scheme_id,)).fetchall()
            
            # 构建节点映射
            name_to_node = {}  # 名称到节点信息的映射
            node_id_map = {}  # 旧ID到新ID的映射（用于边的重映射）
            
            for node in db_nodes:
                node_id = node['id']
                node_name = node['name']
                
                # 存储节点信息
                try:
                    description = node['description']
                except (KeyError, IndexError):
                    description = None
                
                try:
                    document_id = node['document_id']
                except (KeyError, IndexError):
                    document_id = None
                
                name_to_node[node_name] = {
                    'id': node_id,
                    'name': node_name,
                    'type': node['node_type'],
                    'description': description or '',
                    'frequency': node['frequency'],
                    'document_id': document_id
                }
        
        # 转换节点格式，确保每个节点名称只出现一次
        for node_name, node_info in name_to_node.items():
            nodes.append({
                'id': node_info['id'],
                'name': node_info['name'],
                'type': node_info['type'],
                'description': node_info['description'],
                'frequency': node_info['frequency'],
                'document_id': node_info['document_id']
            })
        
        # 获取所有节点名称到ID的映射（用于边的重映射）
        name_to_id_map = {node['name']: node['id'] for node in nodes}
        
        # 获取有效的节点ID集合
        valid_node_ids = {node['id'] for node in nodes}
        
        # 转换边格式，需要根据节点名称重映射边的端点
        with self.db.get_connection() as conn:
            # 获取所有有效的边，并获取源节点和目标节点的名称
            all_edges_query = conn.execute('''
                SELECT DISTINCT 
                    ke.source_id, 
                    ke.target_id, 
                    ke.relation_type, 
                    ke.weight,
                    kn1.name as source_name,
                    kn2.name as target_name
                FROM knowledge_edges ke
                INNER JOIN knowledge_nodes kn1 ON ke.source_id = kn1.id
                INNER JOIN knowledge_nodes kn2 ON ke.target_id = kn2.id
                LEFT JOIN documents d1 ON kn1.document_id = d1.id
                LEFT JOIN documents d2 ON kn2.document_id = d2.id
                WHERE (kn1.document_id IS NULL OR d1.is_deleted = 0)
                AND (kn2.document_id IS NULL OR d2.is_deleted = 0)
                AND (ke.scheme_id = ? OR ke.scheme_id IS NULL)
            ''', (scheme_id,)).fetchall()
            
            # 构建边映射，用于去重
            edge_map = {}
            
            for edge in all_edges_query:
                try:
                    source_name = edge['source_name']
                    target_name = edge['target_name']
                except (KeyError, IndexError):
                    continue
                
                # 如果两个节点都在有效节点集合中，添加边
                if source_name in name_to_id_map and target_name in name_to_id_map:
                    new_source_id = name_to_id_map[source_name]
                    new_target_id = name_to_id_map[target_name]
                    
                    # 避免自环和重复边
                    if new_source_id != new_target_id:
                        edge_key = (new_source_id, new_target_id)
                        if edge_key not in edge_map:
                            try:
                                relation_type = edge['relation_type']
                            except (KeyError, IndexError):
                                relation_type = 'related'
                            
                            try:
                                weight = edge['weight']
                            except (KeyError, IndexError):
                                weight = 1.0
                            
                            edges.append({
                                'source': new_source_id,
                                'target': new_target_id,
                                'type': relation_type,
                                'weight': weight
                            })
                            edge_map[edge_key] = True

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
    
    def delete_document_by_hash(self, hash_value: str) -> bool:
        """根据哈希值删除文档（包括文件和数据库记录）"""
        try:
            with self.db.get_connection() as conn:
                # 查询要删除的文档
                doc = conn.execute(
                    'SELECT id, file_path FROM documents WHERE hash_value = ? AND is_deleted = 0',
                    (hash_value,)
                ).fetchone()
                
                if doc:
                    doc_id = doc['id']
                    file_path = doc['file_path']
                    
                    # 1. 删除uploads文件夹中的文件
                    if file_path and os.path.exists(file_path):
                        try:
                            os.remove(file_path)
                            print(f"已删除文件: {file_path}")
                        except Exception as e:
                            print(f"删除文件失败 {file_path}: {e}")
                            # 即使文件删除失败，也继续删除数据库记录
                    
                    # 2. 删除数据库中的记录（包括哈希值）
                    conn.execute(
                        'DELETE FROM documents WHERE id = ?',
                        (doc_id,)
                    )
                    
                    print(f"已删除文档记录 ID: {doc_id}, 哈希值: {hash_value}")
                    return True
                else:
                    print(f"未找到哈希值为 {hash_value} 的文档")
                    return False
        except Exception as e:
            print(f"根据哈希值删除文档时出错: {e}")
            return False
    
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
    
    def save_document(self, doc_data: Dict[str, Any], force_replace: bool = False) -> Tuple[Optional[int], bool]:
        """保存文档到数据库
        参数:
            doc_data: 文档数据
            force_replace: 如果为True，遇到哈希值冲突时强制删除旧记录并插入新记录
        返回: (文档ID, 是否已存在)
        """
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
                return (cursor.lastrowid, False)  # 新文档
        except sqlite3.IntegrityError as e:
            # 哈希值重复
            if force_replace:
                # 强制替换：删除旧记录并重新插入
                print(f"文档 {doc_data['title']} 已存在（哈希值重复），强制删除旧记录并插入新记录")
                with self.db.get_connection() as conn:
                    # 删除旧记录
                    conn.execute(
                        'DELETE FROM documents WHERE hash_value = ?',
                        (doc_data['hash_value'],)
                    )
                    conn.commit()
                    
                    # 重新插入
                    try:
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
                        return (cursor.lastrowid, False)  # 新文档
                    except Exception as retry_error:
                        print(f"重新插入文档时出错: {retry_error}")
                        return (None, False)
            else:
                # 不强制替换：查询已存在的文档ID
                print(f"文档 {doc_data['title']} 已存在（哈希值重复），返回已存在的文档ID")
                with self.db.get_connection() as conn:
                    existing_doc = conn.execute(
                        'SELECT id FROM documents WHERE hash_value = ? AND is_deleted = 0',
                        (doc_data['hash_value'],)
                    ).fetchone()
                    if existing_doc:
                        return (existing_doc['id'], True)  # 已存在的文档
                return (None, False)
        except Exception as e:
            print(f"保存文档时出错: {e}")
            import traceback
            traceback.print_exc()
            return (None, False)
    
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
    app.config['SESSION_COOKIE_SECURE'] = False  # 开发环境设为False，生产环境应设为True
    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    Config.init_app(app)
    
    # 启用CORS
    CORS(app)
    
    # 认证装饰器
    def login_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if 'user_id' not in session:
                # 如果是 API 请求，返回 JSON 错误
                if request.path.startswith('/api/'):
                    return jsonify({
                        'success': False,
                        'message': '请先登录',
                        'requires_login': True
                    }), 401
                # 否则重定向到登录页
                return redirect(url_for('login'))
            return f(*args, **kwargs)
        return decorated_function
    
    # 密码哈希函数
    def hash_password(password: str) -> str:
        """生成密码哈希"""
        return hash_lib.sha256(password.encode('utf-8')).hexdigest()
    
    # 验证密码
    def verify_password(password: str, password_hash: str) -> bool:
        """验证密码"""
        return hash_password(password) == password_hash
    
    # 初始化各个管理器
    db_manager = DatabaseManager(Config.DATABASE_PATH)
    ai_processor = AIProcessor()
    kg_manager = KnowledgeGraphManager(db_manager)
    doc_manager = DocumentManager(db_manager, ai_processor)
    ai_assistant = AIAssistant()
    
    # 注册路由
    @app.route('/')
    @login_required
    def index():
        """主页"""
        return render_template('index.html')
    
    @app.route('/login')
    def login():
        """登录页面"""
        # 如果已登录，重定向到主页
        if 'user_id' in session:
            return redirect(url_for('index'))
        return render_template('login.html')
    
    @app.route('/register')
    def register():
        """注册页面"""
        # 如果已登录，重定向到主页
        if 'user_id' in session:
            return redirect(url_for('index'))
        return render_template('register.html')
    
    @app.route('/api/auth/login', methods=['POST'])
    def api_login():
        """登录API"""
        try:
            data = request.get_json(force=True, silent=True) or {}
            username = data.get('username', '').strip()
            password = data.get('password', '').strip()
            
            if not username or not password:
                return jsonify({
                    'success': False,
                    'message': '用户名和密码不能为空'
                }), 400
            
            with db_manager.get_connection() as conn:
                # 查找用户（支持用户名或邮箱登录）
                user = conn.execute('''
                    SELECT id, username, email, password_hash 
                    FROM users 
                    WHERE username = ? OR email = ?
                ''', (username, username)).fetchone()
                
                if not user:
                    return jsonify({
                        'success': False,
                        'message': '用户名或密码错误'
                    }), 401
                
                # 验证密码
                if not verify_password(password, user['password_hash']):
                    return jsonify({
                        'success': False,
                        'message': '用户名或密码错误'
                    }), 401
                
                # 更新最后登录时间
                conn.execute('''
                    UPDATE users 
                    SET last_login = CURRENT_TIMESTAMP 
                    WHERE id = ?
                ''', (user['id'],))
                conn.commit()
                
                # 设置会话
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['email'] = user['email']
                
                return jsonify({
                    'success': True,
                    'message': '登录成功',
                    'user': {
                        'id': user['id'],
                        'username': user['username'],
                        'email': user['email']
                    }
                })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'登录失败: {str(e)}'
            }), 500
    
    @app.route('/api/auth/register', methods=['POST'])
    def api_register():
        """注册API"""
        try:
            data = request.get_json(force=True, silent=True) or {}
            username = data.get('username', '').strip()
            email = data.get('email', '').strip()
            password = data.get('password', '').strip()
            
            # 验证输入
            if not username or not email or not password:
                return jsonify({
                    'success': False,
                    'message': '所有字段都不能为空'
                }), 400
            
            if len(password) < 6:
                return jsonify({
                    'success': False,
                    'message': '密码至少需要6个字符'
                }), 400
            
            # 验证邮箱格式
            import re
            email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
            if not re.match(email_pattern, email):
                return jsonify({
                    'success': False,
                    'message': '邮箱格式不正确'
                }), 400
            
            with db_manager.get_connection() as conn:
                # 检查用户名是否已存在
                existing_user = conn.execute('''
                    SELECT id FROM users WHERE username = ?
                ''', (username,)).fetchone()
                
                if existing_user:
                    return jsonify({
                        'success': False,
                        'message': '用户名已存在'
                    }), 400
                
                # 检查邮箱是否已存在
                existing_email = conn.execute('''
                    SELECT id FROM users WHERE email = ?
                ''', (email,)).fetchone()
                
                if existing_email:
                    return jsonify({
                        'success': False,
                        'message': '邮箱已被注册'
                    }), 400
                
                # 创建新用户
                password_hash = hash_password(password)
                cursor = conn.execute('''
                    INSERT INTO users (username, email, password_hash)
                    VALUES (?, ?, ?)
                ''', (username, email, password_hash))
                conn.commit()
                
                user_id = cursor.lastrowid
                
                return jsonify({
                    'success': True,
                    'message': '注册成功',
                    'user': {
                        'id': user_id,
                        'username': username,
                        'email': email
                    }
                })
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'注册失败: {str(e)}'
            }), 500
    
    @app.route('/api/auth/logout', methods=['POST'])
    @login_required
    def api_logout():
        """登出API"""
        session.clear()
        return jsonify({
            'success': True,
            'message': '已登出'
        })
    
    @app.route('/api/auth/check', methods=['GET'])
    def api_check_auth():
        """检查认证状态"""
        if 'user_id' in session:
            return jsonify({
                'success': True,
                'authenticated': True,
                'user': {
                    'id': session.get('user_id'),
                    'username': session.get('username'),
                    'email': session.get('email')
                }
            })
        else:
            return jsonify({
                'success': True,
                'authenticated': False
            })
        
    @app.route('/static/<path:filename>')
    def serve_static(filename):
        return send_from_directory('static', filename)
    
    @app.route('/api/documents', methods=['GET', 'POST'])
    @login_required
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
                allowed_types = ['txt', 'md', 'pdf', 'docx', 'doc', 'ppt', 'pptx']
                
                if file_ext not in allowed_types:
                    return jsonify({
                        'success': False, 
                        'message': f'不支持的文件格式: {file_ext}. 支持的格式: {", ".join(allowed_types)}'
                    }), 400
                
                # 保存文件
                file_path = os.path.join(Config.UPLOAD_FOLDER, filename)
                file.save(file_path)
                
                # 计算文件哈希值
                file_hash = doc_manager.calculate_file_hash(file_path)
                
                # 检查数据库中是否已存在相同哈希值的文件
                is_replacement = False
                old_doc_id = None
                old_file_path = None
                old_title = None
                
                # 先查询是否存在相同哈希值的文件
                with db_manager.get_connection() as conn:
                    existing_doc = conn.execute(
                        'SELECT id, file_path, title FROM documents WHERE hash_value = ? AND is_deleted = 0',
                        (file_hash,)
                    ).fetchone()
                    
                    if existing_doc:
                        is_replacement = True
                        old_doc_id = existing_doc['id']
                        old_file_path = existing_doc['file_path']
                        old_title = existing_doc['title']
                
                # 如果存在旧记录，先删除旧文件（在删除数据库记录之前）
                if is_replacement and old_file_path and old_file_path != file_path and os.path.exists(old_file_path):
                    try:
                        os.remove(old_file_path)
                        print(f"已删除旧文件: {old_file_path}")
                    except Exception as e:
                        print(f"删除旧文件失败 {old_file_path}: {e}")
                
                # 删除数据库中的旧记录（如果存在）
                if is_replacement and old_doc_id:
                    with db_manager.get_connection() as conn:
                        conn.execute(
                            'DELETE FROM documents WHERE id = ?',
                            (old_doc_id,)
                        )
                        conn.commit()  # 显式提交，确保删除操作生效
                        print(f"已删除旧文档记录 ID: {old_doc_id}，哈希值: {file_hash}，旧标题: {old_title}")
                
                # 处理文档
                doc_data = doc_manager.process_document(file_path, filename)
                if not doc_data:
                    return jsonify({'success': False, 'message': '文档处理失败：无法提取文档内容'}), 500
                
                # 确保使用计算好的哈希值
                doc_data['hash_value'] = file_hash
                
                # 保存新文档（如果存在旧记录，强制替换）
                doc_id, is_existing = doc_manager.save_document(doc_data, force_replace=is_replacement)
                if not doc_id:
                    # 如果保存失败，尝试强制删除并重新保存
                    print(f"保存失败，尝试强制删除旧记录并重新保存...")
                    with db_manager.get_connection() as conn:
                        conn.execute(
                            'DELETE FROM documents WHERE hash_value = ?',
                            (file_hash,)
                        )
                        conn.commit()
                    # 再次尝试保存（强制替换）
                    doc_id, is_existing = doc_manager.save_document(doc_data, force_replace=True)
                    
                    if not doc_id:
                        return jsonify({
                            'success': False, 
                            'message': f'文档保存失败：无法保存到数据库。请检查文件是否损坏或数据库是否正常。'
                        }), 500
                
                # 根据是否替换旧文件返回不同的消息
                message = '文档上传成功（已替换旧文件）' if is_replacement else '文档上传成功'
                return jsonify({
                    'success': True,
                    'message': message,
                    'document_id': doc_id,
                    'is_existing': False,
                    'is_replacement': is_replacement,
                    'processing_status': doc_data['metadata']['processing_status'],
                    'processing_message': doc_data['metadata']['processing_message']
                })

    
    @app.route('/api/search')
    @login_required
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
    @login_required
    def get_knowledge_graph():
        """获取知识图谱数据"""
        scheme_id = request.args.get('scheme_id', type=int)
        graph_data = kg_manager.get_graph_data(scheme_id)
        return jsonify({
            'success': True,
            'data': graph_data,
            'node_count': len(graph_data['nodes']),
            'edge_count': len(graph_data['edges']),
            'scheme_id': scheme_id or kg_manager.current_scheme_id
        })
    
    # 知识图谱方案管理
    @app.route('/api/kg/schemes', methods=['GET', 'POST'])
    def kg_schemes():
        """获取方案列表或创建新方案"""
        if request.method == 'GET':
            with db_manager.get_connection() as conn:
                rows = conn.execute('''
                    SELECT * FROM knowledge_graph_schemes 
                    ORDER BY is_default DESC, created_at DESC
                ''').fetchall()
                schemes = [dict(r) for r in rows]
                return jsonify({
                    'success': True, 
                    'data': schemes,
                    'current_scheme_id': kg_manager.current_scheme_id
                })
        else:
            # 创建新方案
            data = request.get_json(force=True, silent=True) or {}
            name = data.get('name', '').strip()
            description = data.get('description', '').strip()
            if not name:
                return jsonify({'success': False, 'message': '方案名称不能为空'}), 400
            
            with db_manager.get_connection() as conn:
                cursor = conn.execute('''
                    INSERT INTO knowledge_graph_schemes (name, description)
                    VALUES (?, ?)
                ''', (name, description))
                scheme_id = cursor.lastrowid
                return jsonify({'success': True, 'id': scheme_id, 'scheme_id': scheme_id})
    
    @app.route('/api/kg/schemes/<int:scheme_id>', methods=['PUT', 'DELETE'])
    def kg_scheme_detail(scheme_id):
        """更新或删除方案"""
        if request.method == 'PUT':
            data = request.get_json(force=True, silent=True) or {}
            fields = []
            params = []
            if 'name' in data:
                fields.append('name = ?')
                params.append(data.get('name'))
            if 'description' in data:
                fields.append('description = ?')
                params.append(data.get('description'))
            if not fields:
                return jsonify({'success': False, 'message': '没有更新字段'}), 400
            params.append(scheme_id)
            with db_manager.get_connection() as conn:
                conn.execute(f'UPDATE knowledge_graph_schemes SET {", ".join(fields)} WHERE id = ?', params)
            return jsonify({'success': True})
        else:
            # 删除方案（同时删除关联的节点和边）
            with db_manager.get_connection() as conn:
                # 获取要删除的节点ID
                node_ids = conn.execute(
                    'SELECT id FROM knowledge_nodes WHERE scheme_id = ?',
                    (scheme_id,)
                ).fetchall()
                node_id_list = [n['id'] for n in node_ids]
                
                # 删除关联的边
                if node_id_list:
                    placeholders = ','.join(['?'] * len(node_id_list))
                    conn.execute(
                        f'DELETE FROM knowledge_edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})',
                        node_id_list + node_id_list
                    )
                
                # 删除节点
                conn.execute('DELETE FROM knowledge_nodes WHERE scheme_id = ?', (scheme_id,))
                
                # 删除方案
                conn.execute('DELETE FROM knowledge_graph_schemes WHERE id = ?', (scheme_id,))
                
                # 如果删除的是当前方案，切换到默认方案
                if kg_manager.current_scheme_id == scheme_id:
                    kg_manager._load_default_scheme()
                    kg_manager._load_graph_from_db()
            
            return jsonify({'success': True})
    
    @app.route('/api/kg/schemes/<int:scheme_id>/switch', methods=['POST'])
    def kg_switch_scheme(scheme_id):
        """切换当前方案"""
        with db_manager.get_connection() as conn:
            scheme = conn.execute(
                'SELECT id FROM knowledge_graph_schemes WHERE id = ?',
                (scheme_id,)
            ).fetchone()
            if not scheme:
                return jsonify({'success': False, 'message': '方案不存在'}), 404
        
        kg_manager.set_current_scheme(scheme_id)
        return jsonify({
            'success': True,
            'scheme_id': scheme_id,
            'message': '方案切换成功'
        })
    
    @app.route('/api/kg/current-scheme', methods=['GET'])
    def kg_current_scheme():
        """获取当前方案"""
        return jsonify({
            'success': True,
            'scheme_id': kg_manager.current_scheme_id
        })
    
    # 知识图谱：节点列表/创建
    @app.route('/api/kg/nodes', methods=['GET', 'POST'])
    def kg_nodes():
        if request.method == 'GET':
            scheme_id = request.args.get('scheme_id', type=int) or kg_manager.current_scheme_id
            with db_manager.get_connection() as conn:
                if scheme_id:
                    rows = conn.execute(
                        'SELECT * FROM knowledge_nodes WHERE scheme_id = ? OR scheme_id IS NULL ORDER BY id DESC',
                        (scheme_id,)
                    ).fetchall()
                else:
                    rows = conn.execute('SELECT * FROM knowledge_nodes ORDER BY id DESC').fetchall()
                return jsonify({'success': True, 'data': [dict(r) for r in rows]})
        else:
            data = request.get_json(force=True, silent=True) or {}
            name = data.get('name', '').strip()
            node_type = (data.get('type') or 'concept').strip() or 'concept'
            description = data.get('description')
            document_id = data.get('document_id')
            scheme_id = data.get('scheme_id') or kg_manager.current_scheme_id
            if not name:
                return jsonify({'success': False, 'message': '节点名称不能为空'}), 400
            if not scheme_id:
                return jsonify({'success': False, 'message': '请先选择一个方案'}), 400
            node_id = kg_manager.add_knowledge_node(name, node_type, description, document_id, scheme_id)
            kg_manager._load_graph_from_db()
            return jsonify({'success': True, 'id': node_id})

    # 知识图谱：节点更新/删除
    @app.route('/api/kg/nodes/<int:node_id>', methods=['PUT', 'DELETE'])
    def kg_node_detail(node_id):
        if request.method == 'PUT':
            data = request.get_json(force=True, silent=True) or {}
            fields = []
            params = []
            if 'name' in data:
                fields.append('name = ?')
                params.append(data.get('name'))
            if 'type' in data:
                fields.append('node_type = ?')
                params.append(data.get('type'))
            if 'description' in data:
                fields.append('description = ?')
                params.append(data.get('description'))
            if 'document_id' in data:
                fields.append('document_id = ?')
                params.append(data.get('document_id'))
            if not fields:
                return jsonify({'success': False, 'message': '没有更新字段'}), 400
            params.append(node_id)
            with db_manager.get_connection() as conn:
                conn.execute(f'UPDATE knowledge_nodes SET {", ".join(fields)} WHERE id = ?', params)
            kg_manager._load_graph_from_db()
            return jsonify({'success': True})
        else:
            with db_manager.get_connection() as conn:
                conn.execute('DELETE FROM knowledge_edges WHERE source_id = ? OR target_id = ?', (node_id, node_id))
                conn.execute('DELETE FROM knowledge_nodes WHERE id = ?', (node_id,))
            kg_manager._load_graph_from_db()
            return jsonify({'success': True})

    # 知识图谱：边列表/创建
    @app.route('/api/kg/edges', methods=['GET', 'POST'])
    def kg_edges():
        if request.method == 'GET':
            scheme_id = request.args.get('scheme_id', type=int) or kg_manager.current_scheme_id
            with db_manager.get_connection() as conn:
                if scheme_id:
                    rows = conn.execute(
                        'SELECT * FROM knowledge_edges WHERE scheme_id = ? OR scheme_id IS NULL ORDER BY id DESC',
                        (scheme_id,)
                    ).fetchall()
                else:
                    rows = conn.execute('SELECT * FROM knowledge_edges ORDER BY id DESC').fetchall()
                return jsonify({'success': True, 'data': [dict(r) for r in rows]})
        else:
            data = request.get_json(force=True, silent=True) or {}
            try:
                source_id = int(data.get('source_id'))
                target_id = int(data.get('target_id'))
            except (TypeError, ValueError):
                return jsonify({'success': False, 'message': 'source_id 和 target_id 必须为整数'}), 400
            relation_type = (data.get('relation_type') or 'related').strip() or 'related'
            try:
                weight = float(data.get('weight', 1.0))
            except (TypeError, ValueError):
                weight = 1.0
            scheme_id = data.get('scheme_id') or kg_manager.current_scheme_id
            if not scheme_id:
                return jsonify({'success': False, 'message': '请先选择一个方案'}), 400
            edge_id = kg_manager.add_knowledge_edge(source_id, target_id, relation_type, weight, scheme_id)
            kg_manager._load_graph_from_db()
            return jsonify({'success': True, 'id': edge_id})

    # 知识图谱：边删除
    @app.route('/api/kg/edges/<int:edge_id>', methods=['DELETE'])
    def kg_edge_detail(edge_id):
        with db_manager.get_connection() as conn:
            conn.execute('DELETE FROM knowledge_edges WHERE id = ?', (edge_id,))
        kg_manager._load_graph_from_db()
        return jsonify({'success': True})
    
    @app.route('/knowledge-graph')
    def knowledge_graph_page():
        """知识图谱可视化页面"""
        return render_template('knowledge_graph.html')

    @app.route('/api/knowledge-graph/search')
    def search_knowledge_graph():
        """搜索知识图谱
        搜索节点时，显示与该节点建立了关系的节点以及它们之间的关系
        """
        query = request.args.get('q', '')
        scheme_id = request.args.get('scheme_id', type=int)
        if not query:
            return jsonify({'success': False, 'message': '搜索关键词不能为空'}), 400
    
        try:
            # 获取完整的图谱数据
            graph_data = kg_manager.get_graph_data(scheme_id)
        
            # 第一步：过滤包含搜索词的节点（不区分大小写）
            matched_nodes = [
                node for node in graph_data['nodes'] 
                if query.lower() in node['name'].lower() or 
                (node.get('description') and query.lower() in node['description'].lower())
            ]
        
            # 获取匹配节点的ID集合（统一转换为字符串）
            matched_node_ids = {str(node['id']) for node in matched_nodes}
            
            # 如果没有匹配的节点，返回空结果
            if not matched_node_ids:
                return jsonify({
                    'success': True,
                    'data': {
                        'nodes': [],
                        'edges': []
                    },
                    'original_count': len(graph_data['nodes']),
                    'filtered_count': 0,
                    'related_count': 0
                })
            
            # 第二步：找到所有与匹配节点有关系的边
            related_edges = [
                edge for edge in graph_data['edges'] 
                if str(edge['source']) in matched_node_ids or str(edge['target']) in matched_node_ids
            ]
            
            # 第三步：收集所有相关节点的ID（包括匹配节点和与它们有关系的节点）
            related_node_ids = set(matched_node_ids)
            for edge in related_edges:
                related_node_ids.add(str(edge['source']))
                related_node_ids.add(str(edge['target']))
            
            # 第四步：获取所有相关节点的完整信息
            all_related_nodes = [
                node for node in graph_data['nodes']
                if str(node['id']) in related_node_ids
            ]
            
            # 第五步：获取所有相关节点之间的关系（包括相关节点之间的边）
            # 过滤边：只保留两个端点都在相关节点集合中的边
            final_edges = [
                edge for edge in graph_data['edges']
                if str(edge['source']) in related_node_ids and str(edge['target']) in related_node_ids
            ]
        
            return jsonify({
                'success': True,
                'data': {
                    'nodes': all_related_nodes,
                    'edges': final_edges
                },
                'original_count': len(graph_data['nodes']),
                'matched_count': len(matched_nodes),
                'related_count': len(all_related_nodes) - len(matched_nodes)
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
    @login_required
    def get_study_time():
        """获取学习时长统计（基于真实用户行为数据）"""
        period = request.args.get('period', 'week')
        user_id = session.get('user_id', 1)
        
        with db_manager.get_connection() as conn:
            if period == 'week':
                # 获取最近7天的学习时长
                labels = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']
                values = []
                from datetime import datetime, timedelta
                today = datetime.now().date()
                
                for i in range(6, -1, -1):  # 从6天前到今天
                    target_date = today - timedelta(days=i)
                    start_time = datetime.combine(target_date, datetime.min.time())
                    end_time = datetime.combine(target_date, datetime.max.time())
                    
                    # 查询该天的学习时长（秒转小时）
                    result = conn.execute('''
                        SELECT COALESCE(SUM(duration), 0) as total_duration
                        FROM user_behaviors
                        WHERE user_id = ?
                        AND timestamp >= ? AND timestamp < ?
                        AND action_type IN ('view', 'read', 'study')
                    ''', (user_id, start_time.isoformat(), end_time.isoformat())).fetchone()
                    
                    hours = round(result['total_duration'] / 3600.0, 1) if result['total_duration'] else 0.0
                    values.append(hours)
                    
            elif period == 'month':
                # 获取最近4周的学习时长
                labels = [f'第{i}周' for i in range(1, 5)]
                values = []
                from datetime import datetime, timedelta
                today = datetime.now().date()
                
                for i in range(3, -1, -1):  # 最近4周
                    week_start = today - timedelta(days=today.weekday() + 7 * i)
                    week_end = week_start + timedelta(days=6)
                    start_time = datetime.combine(week_start, datetime.min.time())
                    end_time = datetime.combine(week_end, datetime.max.time())
                    
                    result = conn.execute('''
                        SELECT COALESCE(SUM(duration), 0) as total_duration
                        FROM user_behaviors
                        WHERE user_id = ? 
                        AND timestamp >= ? AND timestamp <= ?
                        AND action_type IN ('view', 'read', 'study')
                    ''', (user_id, start_time.isoformat(), end_time.isoformat())).fetchone()
                    
                    hours = round(result['total_duration'] / 3600.0, 1) if result['total_duration'] else 0.0
                    values.append(hours)
                    
            else:  # quarter
                # 获取最近3个月的学习时长
                labels = ['第1月', '第2月', '第3月']
                values = []
                from datetime import datetime, timedelta
                
                today = datetime.now()
                for i in range(2, -1, -1):  # 最近3个月
                    # 计算月份开始和结束
                    month = today.month - i
                    year = today.year
                    if month <= 0:
                        month += 12
                        year -= 1
                    
                    month_start = datetime(year, month, 1)
                    if month == 12:
                        month_end = datetime(year + 1, 1, 1) - timedelta(days=1)
                    else:
                        month_end = datetime(year, month + 1, 1) - timedelta(days=1)
                    
                    if i == 0:
                        month_end = today
                    
                    result = conn.execute('''
                        SELECT COALESCE(SUM(duration), 0) as total_duration
                        FROM user_behaviors
                        WHERE user_id = ? 
                        AND timestamp >= ? AND timestamp <= ?
                        AND action_type IN ('view', 'read', 'study')
                    ''', (user_id, month_start.isoformat(), month_end.isoformat())).fetchone()
                    
                    hours = round(result['total_duration'] / 3600.0, 1) if result['total_duration'] else 0.0
                    values.append(hours)
            
            # 计算总时长和平均时长
            total_hours = sum(values)
            avg_hours = round(total_hours / len(values), 1) if values else 0.0
        
        return jsonify({
            'success': True,
            'data': {
                'labels': labels,
                'values': values,
                'period': period,
                'total_hours': total_hours,
                'avg_hours': avg_hours
            }
        })
    
    @app.route('/api/analytics/knowledge-level')
    def get_knowledge_level():
        """获取知识点掌握分布（统计来自已上传文件的所有类型节点）"""
        with db_manager.get_connection() as conn:
            # 统计来自未删除文档的所有类型节点
            total_nodes = conn.execute('''
                SELECT COUNT(*) FROM knowledge_nodes kn
                LEFT JOIN documents d ON kn.document_id = d.id
                WHERE (kn.document_id IS NULL OR d.is_deleted = 0)
            ''').fetchone()[0]
            
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
            # 统计来自未删除文档的所有类型节点
            total_nodes = conn.execute('''
                SELECT COUNT(*) FROM knowledge_nodes kn
                LEFT JOIN documents d ON kn.document_id = d.id
                WHERE (kn.document_id IS NULL OR d.is_deleted = 0)
            ''').fetchone()[0]
            
            # 统计关系数量
            total_edges = conn.execute('SELECT COUNT(*) FROM knowledge_edges').fetchone()[0]
            
            # 简化的预测算法
            # 假设目标：100个文档，200个知识点，300个关系
            target_docs = 100
            target_nodes = 200
            target_edges = 300
            
            doc_progress = min(100, int((total_docs / target_docs) * 100)) if target_docs > 0 else 0
            node_progress = min(100, int((total_nodes / target_nodes) * 100)) if target_nodes > 0 else 0
            edge_progress = min(100, int((total_edges / target_edges) * 100)) if target_edges > 0 else 0
            overall_progress = int((doc_progress + node_progress + edge_progress) / 3)
            
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
            if total_edges < 30:
                recommendations.append('建立更多知识点之间的关联，完善知识网络')
            if total_docs > 0 and total_nodes > 0 and total_edges == 0:
                recommendations.append('为知识点建立关联关系，形成知识网络')
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
                'doc_progress': doc_progress,
                'node_progress': node_progress,
                'edge_progress': edge_progress,
                'estimated_time': estimated_time,
                'recommended_time': '2小时/天',
                'recommendations': recommendations[:3]  # 最多3条建议
            }
        })
    
    @app.route('/api/analytics/progress')
    def get_learning_progress():
        """获取学习进度跟踪"""
        with db_manager.get_connection() as conn:
            # 获取文档统计
            total_docs = conn.execute('SELECT COUNT(*) FROM documents WHERE is_deleted = 0').fetchone()[0]
            
            # 获取节点统计（按类型分组）
            nodes_by_type = conn.execute('''
                SELECT node_type, COUNT(*) as count
                FROM knowledge_nodes kn
                LEFT JOIN documents d ON kn.document_id = d.id
                WHERE (kn.document_id IS NULL OR d.is_deleted = 0)
                GROUP BY node_type
            ''').fetchall()
            
            # 获取关系统计
            total_edges = conn.execute('SELECT COUNT(*) FROM knowledge_edges').fetchone()[0]
            
            # 获取最近的学习活动
            recent_activities = conn.execute('''
                SELECT action_type, COUNT(*) as count, MAX(timestamp) as last_time
                FROM user_behaviors
                WHERE action_type IN ('view', 'read', 'study', 'upload')
                GROUP BY action_type
                ORDER BY last_time DESC
                LIMIT 5
            ''').fetchall()
            
            # 计算学习天数
            first_doc = conn.execute('''
                SELECT MIN(created_at) as first_date
                FROM documents
                WHERE is_deleted = 0
            ''').fetchone()
            
            learning_days = 0
            if first_doc and first_doc['first_date']:
                from datetime import datetime
                try:
                    if isinstance(first_doc['first_date'], str):
                        first_date = datetime.fromisoformat(first_doc['first_date'].replace('Z', '+00:00'))
                    else:
                        first_date = first_doc['first_date']
                    learning_days = (datetime.now() - first_date).days + 1
                except:
                    learning_days = 1
        
        return jsonify({
            'success': True,
            'data': {
                'total_docs': total_docs,
                'total_nodes': sum(n['count'] for n in nodes_by_type),
                'nodes_by_type': [{'type': n['node_type'], 'count': n['count']} for n in nodes_by_type],
                'total_edges': total_edges,
                'learning_days': learning_days,
                'recent_activities': [{'type': a['action_type'], 'count': a['count'], 'last_time': a['last_time']} for a in recent_activities]
            }
        })
    
    @app.route('/api/analytics/growth')
    def get_knowledge_growth():
        """获取知识网络成长轨迹"""
        period = request.args.get('period', 'month')  # month, week, day
        with db_manager.get_connection() as conn:
            from datetime import datetime, timedelta
            
            if period == 'day':
                # 最近30天的成长轨迹
                labels = []
                node_counts = []
                edge_counts = []
                doc_counts = []
                
                for i in range(29, -1, -1):
                    target_date = datetime.now().date() - timedelta(days=i)
                    date_str = target_date.strftime('%m-%d')
                    labels.append(date_str)
                    
                    # 统计到该日期为止的累计数量
                    end_time = datetime.combine(target_date, datetime.max.time())
                    
                    node_count = conn.execute('''
                        SELECT COUNT(*) as count
                        FROM knowledge_nodes kn
                        LEFT JOIN documents d ON kn.document_id = d.id
                        WHERE (kn.document_id IS NULL OR d.is_deleted = 0)
                        AND kn.created_at <= ?
                    ''', (end_time.isoformat(),)).fetchone()[0]
                    
                    edge_count = conn.execute('''
                        SELECT COUNT(*) as count
                        FROM knowledge_edges
                        WHERE created_at <= ?
                    ''', (end_time.isoformat(),)).fetchone()[0]
                    
                    doc_count = conn.execute('''
                        SELECT COUNT(*) as count
                        FROM documents
                        WHERE is_deleted = 0 AND created_at <= ?
                    ''', (end_time.isoformat(),)).fetchone()[0]
                    
                    node_counts.append(node_count)
                    edge_counts.append(edge_count)
                    doc_counts.append(doc_count)
                    
            elif period == 'week':
                # 最近12周的成长轨迹
                labels = []
                node_counts = []
                edge_counts = []
                doc_counts = []
                
                today = datetime.now().date()
                for i in range(11, -1, -1):
                    week_start = today - timedelta(days=today.weekday() + 7 * i)
                    week_end = week_start + timedelta(days=6)
                    labels.append(f'{week_start.strftime("%m-%d")}')
                    
                    end_time = datetime.combine(week_end, datetime.max.time())
                    
                    node_count = conn.execute('''
                        SELECT COUNT(*) as count
                        FROM knowledge_nodes kn
                        LEFT JOIN documents d ON kn.document_id = d.id
                        WHERE (kn.document_id IS NULL OR d.is_deleted = 0)
                        AND kn.created_at <= ?
                    ''', (end_time.isoformat(),)).fetchone()[0]
                    
                    edge_count = conn.execute('''
                        SELECT COUNT(*) as count
                        FROM knowledge_edges
                        WHERE created_at <= ?
                    ''', (end_time.isoformat(),)).fetchone()[0]
                    
                    doc_count = conn.execute('''
                        SELECT COUNT(*) as count
                        FROM documents
                        WHERE is_deleted = 0 AND created_at <= ?
                    ''', (end_time.isoformat(),)).fetchone()[0]
                    
                    node_counts.append(node_count)
                    edge_counts.append(edge_count)
                    doc_counts.append(doc_count)
                    
            else:  # month
                # 最近12个月的成长轨迹
                labels = []
                node_counts = []
                edge_counts = []
                doc_counts = []
                
                today = datetime.now()
                for i in range(11, -1, -1):
                    month = today.month - i
                    year = today.year
                    if month <= 0:
                        month += 12
                        year -= 1
                    
                    labels.append(f'{year}-{month:02d}')
                    
                    if month == 12:
                        month_end = datetime(year + 1, 1, 1) - timedelta(days=1)
                    else:
                        month_end = datetime(year, month + 1, 1) - timedelta(days=1)
                    
                    if i == 0:
                        month_end = today
                    
                    node_count = conn.execute('''
                        SELECT COUNT(*) as count
                        FROM knowledge_nodes kn
                        LEFT JOIN documents d ON kn.document_id = d.id
                        WHERE (kn.document_id IS NULL OR d.is_deleted = 0)
                        AND kn.created_at <= ?
                    ''', (month_end.isoformat(),)).fetchone()[0]
                    
                    edge_count = conn.execute('''
                        SELECT COUNT(*) as count
                        FROM knowledge_edges
                        WHERE created_at <= ?
                    ''', (month_end.isoformat(),)).fetchone()[0]
                    
                    doc_count = conn.execute('''
                        SELECT COUNT(*) as count
                        FROM documents
                        WHERE is_deleted = 0 AND created_at <= ?
                    ''', (month_end.isoformat(),)).fetchone()[0]
                    
                    node_counts.append(node_count)
                    edge_counts.append(edge_count)
                    doc_counts.append(doc_count)
        
        return jsonify({
            'success': True,
            'data': {
                'labels': labels,
                'node_counts': node_counts,
                'edge_counts': edge_counts,
                'doc_counts': doc_counts,
                'period': period
            }
        })
    
    @app.route('/api/analytics/report')
    def generate_learning_report():
        """生成学习报告"""
        report_type = request.args.get('type', 'full')  # full, summary, detailed
        with db_manager.get_connection() as conn:
            from datetime import datetime
            
            # 基础统计
            total_docs = conn.execute('SELECT COUNT(*) FROM documents WHERE is_deleted = 0').fetchone()[0]
            total_nodes = conn.execute('''
                SELECT COUNT(*) FROM knowledge_nodes kn
                LEFT JOIN documents d ON kn.document_id = d.id
                WHERE (kn.document_id IS NULL OR d.is_deleted = 0)
            ''').fetchone()[0]
            total_edges = conn.execute('SELECT COUNT(*) FROM knowledge_edges').fetchone()[0]
            
            # 节点类型分布
            nodes_by_type = conn.execute('''
                SELECT node_type, COUNT(*) as count
                FROM knowledge_nodes kn
                LEFT JOIN documents d ON kn.document_id = d.id
                WHERE (kn.document_id IS NULL OR d.is_deleted = 0)
                GROUP BY node_type
            ''').fetchall()
            
            # 最近活动
            recent_docs = conn.execute('''
                SELECT title, created_at, file_type
                FROM documents
                WHERE is_deleted = 0
                ORDER BY created_at DESC
                LIMIT 5
            ''').fetchall()
            
            # 学习时长统计（最近7天）
            from datetime import timedelta
            study_time_data = []
            for i in range(6, -1, -1):
                target_date = datetime.now().date() - timedelta(days=i)
                start_time = datetime.combine(target_date, datetime.min.time())
                end_time = datetime.combine(target_date, datetime.max.time())
                
                result = conn.execute('''
                    SELECT COALESCE(SUM(duration), 0) as total_duration
                    FROM user_behaviors
                    WHERE timestamp >= ? AND timestamp < ?
                    AND action_type IN ('view', 'read', 'study')
                ''', (start_time.isoformat(), end_time.isoformat())).fetchone()
                
                hours = round(result['total_duration'] / 3600.0, 1) if result['total_duration'] else 0.0
                study_time_data.append({
                    'date': target_date.strftime('%Y-%m-%d'),
                    'hours': hours
                })
            
            # 生成报告
            report = {
                'generated_at': datetime.now().isoformat(),
                'summary': {
                    'total_documents': total_docs,
                    'total_knowledge_nodes': total_nodes,
                    'total_relationships': total_edges,
                    'knowledge_network_density': round(total_edges / total_nodes, 2) if total_nodes > 0 else 0
                },
                'node_distribution': [{'type': n['node_type'], 'count': n['count']} for n in nodes_by_type],
                'recent_documents': [{'title': d['title'], 'date': d['created_at'], 'type': d['file_type']} for d in recent_docs],
                'study_time_week': study_time_data,
                'total_study_hours': round(sum(s['hours'] for s in study_time_data), 1)
            }
        
        return jsonify({
            'success': True,
            'data': report
        })
    
    @app.route('/api/documents/<int:doc_id>')
    def get_document_detail(doc_id):
        """获取文档详情"""
        try:
            with db_manager.get_connection() as conn:
                doc = conn.execute(
                    'SELECT * FROM documents WHERE id = ? AND is_deleted = 0',
                    (doc_id,)
                ).fetchone()
                
                if not doc:
                    return jsonify({'success': False, 'message': '文档不存在'}), 404
                
                # 读取完整内容
                full_content = None
                # 首先尝试从文件重新提取
                if doc['file_path'] and os.path.exists(doc['file_path']):
                    try:
                        # 从文件路径自动判断文件类型，确保正确
                        actual_file_type = os.path.splitext(doc['file_path'])[1][1:].lower()
                        extracted_content = doc_manager.doc_processor.extract_text(doc['file_path'], actual_file_type)
                        
                        # 如果提取的内容不是错误信息（不以[开头），则使用它
                        if extracted_content and not extracted_content.strip().startswith('['):
                            full_content = extracted_content
                        else:
                            # 如果提取失败，尝试使用数据库中存储的内容
                            print(f"文件提取返回错误信息: {extracted_content[:100]}")
                    except Exception as e:
                        print(f"从文件提取内容失败: {e}")
                        import traceback
                        traceback.print_exc()
                
                # 如果提取失败，使用数据库中存储的内容
                if not full_content:
                    stored_content = doc['content'] or ''
                    # 如果存储的内容也是错误信息，尝试重新处理
                    if stored_content.startswith('[') and doc['file_path'] and os.path.exists(doc['file_path']):
                        # 对于.doc文件，提供更友好的提示
                        actual_file_type = os.path.splitext(doc['file_path'])[1][1:].lower()
                        if actual_file_type == 'doc':
                            full_content = "[.doc格式文档需要特殊处理库。建议：\n1. 安装textract库: pip install textract\n2. 或在Windows系统上安装pywin32: pip install pywin32\n3. 或将文档转换为.docx格式]"
                        else:
                            full_content = stored_content
                    else:
                        full_content = stored_content or '无内容'
                
                doc_dict = dict(doc)
                doc_dict['full_content'] = full_content
                
                # 解析JSON字段
                if doc_dict.get('tags'):
                    try:
                        doc_dict['tags'] = json.loads(doc_dict['tags'])
                    except:
                        doc_dict['tags'] = []
                else:
                    doc_dict['tags'] = []
                
                if doc_dict.get('metadata'):
                    try:
                        doc_dict['metadata'] = json.loads(doc_dict['metadata'])
                    except:
                        doc_dict['metadata'] = {}
                else:
                    doc_dict['metadata'] = {}
                
                return jsonify({
                    'success': True,
                    'data': doc_dict
                })
        except Exception as e:
            print(f"获取文档详情失败: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': f'获取文档详情失败: {str(e)}'
            }), 500
    
    @app.route('/api/documents/<int:doc_id>/download')
    @login_required
    def download_document(doc_id):
        """下载文档"""
        try:
            with db_manager.get_connection() as conn:
                doc = conn.execute(
                    'SELECT file_path, title, file_type FROM documents WHERE id = ? AND is_deleted = 0',
                    (doc_id,)
                ).fetchone()
                
                if not doc:
                    return jsonify({
                        'success': False,
                        'message': '文档不存在'
                    }), 404
                
                file_path = doc['file_path']
                
                if not file_path or not os.path.exists(file_path):
                    return jsonify({
                        'success': False,
                        'message': '文件不存在'
                    }), 404
                
                # 获取原始文件名或使用标题
                original_filename = doc['title']
                if not original_filename.endswith('.' + doc['file_type']):
                    original_filename = f"{original_filename}.{doc['file_type']}"
                
                return send_file(
                    file_path,
                    as_attachment=True,
                    download_name=original_filename,
                    mimetype='application/octet-stream'
                )
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'下载失败: {str(e)}'
            }), 500
    
    @app.route('/api/documents/<int:doc_id>', methods=['DELETE'])
    def delete_document(doc_id):
        """删除文档（硬删除：删除文件、数据库记录和哈希值）"""
        try:
            with db_manager.get_connection() as conn:
                # 先获取文档信息（包括文件路径和哈希值）
                doc = conn.execute(
                    'SELECT file_path, hash_value FROM documents WHERE id = ?',
                    (doc_id,)
                ).fetchone()
                
                if not doc:
                    return jsonify({
                        'success': False,
                        'message': '文档不存在'
                    }), 404
                
                file_path = doc['file_path']
                hash_value = doc['hash_value']
                
                # 1. 删除uploads文件夹中的文件
                if file_path and os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        print(f"已删除文件: {file_path}")
                    except Exception as e:
                        print(f"删除文件失败 {file_path}: {e}")
                        # 即使文件删除失败，也继续删除数据库记录
                
                # 2. 获取要删除的知识节点ID（用于从内存图中移除）
                node_ids_to_delete = conn.execute(
                    'SELECT id FROM knowledge_nodes WHERE document_id = ?',
                    (doc_id,)
                ).fetchall()
                node_ids = [node['id'] for node in node_ids_to_delete]
                
                # 3. 删除关联的知识节点（所有类型）
                cursor = conn.execute(
                    'DELETE FROM knowledge_nodes WHERE document_id = ?',
                    (doc_id,)
                )
                deleted_nodes = cursor.rowcount
                if deleted_nodes > 0:
                    print(f"已删除 {deleted_nodes} 个关联的知识节点")
                
                # 4. 删除关联的知识边（如果源节点或目标节点被删除）
                if node_ids:
                    placeholders = ','.join(['?'] * len(node_ids))
                    cursor = conn.execute(
                        f'DELETE FROM knowledge_edges WHERE source_id IN ({placeholders}) OR target_id IN ({placeholders})',
                        node_ids + node_ids
                    )
                    deleted_edges = cursor.rowcount
                    if deleted_edges > 0:
                        print(f"已删除 {deleted_edges} 条关联的知识边")
                
                # 5. 删除数据库中的记录（硬删除：彻底从数据库中删除）
                cursor = conn.execute(
                    'DELETE FROM documents WHERE id = ?',
                    (doc_id,)
                )
                deleted_doc = cursor.rowcount
                
                if deleted_doc == 0:
                    return jsonify({
                        'success': False,
                        'message': '文档删除失败，记录不存在'
                    }), 404
                
                # 提交事务，确保所有删除操作生效
                conn.commit()
                
                print(f"已删除文档记录 ID: {doc_id}, 哈希值: {hash_value}")
                
                # 6. 从内存中的知识图谱移除已删除的节点
                for node_id in node_ids:
                    if node_id in kg_manager.graph:
                        kg_manager.graph.remove_node(node_id)
                        print(f"从内存图谱中移除节点 ID: {node_id}")
                
            return jsonify({
                'success': True,
                'message': '文档已彻底删除'
            })
        except Exception as e:
            print(f"删除文档时发生错误: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                'success': False,
                'message': f'删除失败: {str(e)}'
            }), 500
    
    # AI学习助手API
    @app.route('/api/ai-assistant/chat', methods=['POST'])
    def ai_chat():
        """AI对话接口"""
        try:
            data = request.get_json(force=True, silent=True) or {}
            user_message = data.get('message', '').strip()
            
            if not user_message:
                return jsonify({
                    'success': False,
                    'message': '消息内容不能为空'
                }), 400
            
            # 获取对话历史（可选）
            context = data.get('context', [])
            
            # 调用AI助手
            result = ai_assistant.chat(user_message, context)
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'处理请求失败: {str(e)}'
            }), 500
    
    @app.route('/api/ai-assistant/suggestion', methods=['POST'])
    def ai_suggestion():
        """获取学习建议"""
        try:
            data = request.get_json(force=True, silent=True) or {}
            topic = data.get('topic', '').strip()
            
            if not topic:
                return jsonify({
                    'success': False,
                    'message': '学习主题不能为空'
                }), 400
            
            # 获取用户文档列表（可选）
            user_documents = []
            if data.get('include_documents', False):
                with db_manager.get_connection() as conn:
                    docs = conn.execute(
                        'SELECT id, title, content FROM documents WHERE is_deleted = 0 ORDER BY created_at DESC LIMIT 10'
                    ).fetchall()
                    user_documents = [dict(doc) for doc in docs]
            
            # 调用AI助手获取建议
            result = ai_assistant.get_learning_suggestion(topic, user_documents)
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'处理请求失败: {str(e)}'
            }), 500
    
    @app.route('/api/ai-assistant/explain', methods=['POST'])
    def ai_explain():
        """解释概念"""
        try:
            data = request.get_json(force=True, silent=True) or {}
            concept = data.get('concept', '').strip()
            
            if not concept:
                return jsonify({
                    'success': False,
                    'message': '概念名称不能为空'
                }), 400
            
            # 查找相关文档
            related_docs = []
            if data.get('search_documents', True):
                results = doc_manager.search_documents(concept, limit=3)
                related_docs = results
            
            # 调用AI助手解释概念
            result = ai_assistant.explain_concept(concept, related_docs)
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'处理请求失败: {str(e)}'
            }), 500
    
    @app.route('/api/ai-assistant/review-plan', methods=['POST'])
    def ai_review_plan():
        """生成复习计划"""
        try:
            data = request.get_json(force=True, silent=True) or {}
            knowledge_points = data.get('knowledge_points', [])
            
            if not knowledge_points or not isinstance(knowledge_points, list):
                return jsonify({
                    'success': False,
                    'message': '知识点列表不能为空'
                }), 400
            
            # 调用AI助手生成复习计划
            result = ai_assistant.generate_review_plan(knowledge_points)
            
            return jsonify(result)
            
        except Exception as e:
            return jsonify({
                'success': False,
                'message': f'处理请求失败: {str(e)}'
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