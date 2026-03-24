#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from flask import Flask, render_template_string, request, jsonify
from agent.loop import AgentLoop
import config

app = Flask(__name__)

# 全局 agent 实例（简单起见，单用户）
agent = None

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>迁移助手 Web 版</title>
    <style>
        body { font-family: sans-serif; margin: 20px; }
        #chat { border: 1px solid #ccc; padding: 10px; height: 400px; overflow-y: scroll; margin-bottom: 10px; }
        .user { color: blue; margin: 5px 0; }
        .assistant { color: green; margin: 5px 0; }
        .system { color: gray; margin: 5px 0; }
        #input { width: 80%; padding: 5px; }
        button { padding: 5px 15px; }
    </style>
</head>
<body>
    <h2>迁移助手 Web 版</h2>
    <div id="chat"></div>
    <input type="text" id="input" placeholder="输入消息..." autofocus>
    <button onclick="sendMessage()">发送</button>
    <script>
        function addMessage(role, text) {
            const chat = document.getElementById('chat');
            const div = document.createElement('div');
            div.className = role;
            div.innerHTML = `<strong>${role}:</strong> ${text.split("\\n").join("<br>")}`;
            chat.appendChild(div);
            chat.scrollTop = chat.scrollHeight;
        }
        async function sendMessage() {
            const input = document.getElementById('input');
            const text = input.value.trim();
            if (!text) return;
            addMessage('user', text);
            input.value = '';
            input.focus();
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: text })
            });
            const data = await response.json();
            addMessage('assistant', data.response);
        }
        document.getElementById('input').addEventListener('keypress', function(e) {
            if (e.key === 'Enter') sendMessage();
        });
        // 页面加载时初始化会话
        window.onload = async function() {
            const response = await fetch('/init', { method: 'POST' });
            const data = await response.json();
            addMessage('system', data.message);
            if (data.initial_response) {
                addMessage('assistant', data.initial_response);
            }
        };
    </script>
</body>
</html>
'''


@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)


@app.route('/init', methods=['POST'])
def init_session():
    global agent
    if agent is None:
        agent = AgentLoop()
        initial_task = "请探索当前工程，并准备协助我完成迁移相关工作。"
        try:
            response = agent.start_session(initial_task)
            return jsonify({
                'message': '会话已初始化',
                'initial_response': response
            })
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    else:
        return jsonify({'message': '会话已存在', 'initial_response': None})


@app.route('/chat', methods=['POST'])
def chat():
    global agent
    if agent is None:
        return jsonify({'error': '会话未初始化'}), 400
    data = request.get_json()
    user_message = data.get('message', '').strip()
    if not user_message:
        return jsonify({'error': '消息为空'}), 400
    try:
        response = agent.send_user_message(user_message)
        return jsonify({'response': response})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


if __name__ == '__main__':
    host = config.get("web.host", "0.0.0.0")
    port = config.get("web.port", 5001)
    debug = config.get("web.debug", True)
    print(f'启动迁移助手 Web 版，请访问 http://localhost:{port}')
    app.run(debug=debug, host=host, port=port)
