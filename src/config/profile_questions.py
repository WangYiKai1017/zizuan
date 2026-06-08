# src/config/profile_questions.py

class ProfileQuestionBank:
    """用户画像问题库"""
    
    # 基础信息问题集
    BASIC_QUESTIONS = {
        "name": {
            "question": "您好，很高兴认识您。请问您怎么称呼？",
            "field": "name",
            "optional": False,
            "follow_ups": [
                "那您希望我怎么称呼您呢？"
            ]
        },
        "age": {
            "question": "请问您今年高寿了？",
            "field": "age",
            "optional": False,
            "validation": "age >= 60",  # 验证条件
        },
        "occupation": {
            "question": "您以前是做什么工作的？",
            "field": "occupation",
            "optional": False,
            "follow_ups": [
                "那份工作您做了多长时间呢？",
                "工作中最难忘的事情是什么？"
            ]
        },
        "birth_place": {
            "question": "您是在哪儿出生的？",
            "field": "birth_place",
            "optional": True,
        },
        "retirement_year": {
            "question": "您退休有多少年了？",
            "field": "retirement_year",
            "optional": True,
        },
    }
    
    # 详细信息问题集
    DETAIL_QUESTIONS = {
        "family_status": {
            "question": "您的家庭状况是怎样的？",
            "field": "family_status",
            "optional": False,
            "options": ["已婚", "丧偶", "离异", "未婚"],
        },
        "children": {
            "question": "您有几个孩子？他们都多大了？",
            "field": "children_count",
            "optional": True,
            "condition": "family_status == 'married' or family_status == 'widowed'",  # 条件触发
        },
        "living_arrangement": {
            "question": "您现在是和家人一起住，还是独居？",
            "field": "living_arrangement",
            "optional": False,
            "options": ["与子女同住", "与老伴同住", "独居", "养老院/敬老院"],
        },
        "health_status": {
            "question": "您的身体状况怎么样？",
            "field": "health_status",
            "optional": True,
            "options": ["很好", "还不错", "一般", "不太好"],
        },
        "important_person": {
            "question": "在您的生命中，有没有对您影响特别大的人？",
            "field": "important_person",
            "optional": True,
            "is_open": True,
        },
        "favorite_memory": {
            "question": "您最美好的回忆是什么？",
            "field": "favorite_memory",
            "optional": True,
            "is_open": True,
        },
    }
    
    # 过渡话术
    TRANSITION_PHRASES = {
        "to_basic": "为了更好地记录您的故事，我想先简单了解一下您的情况。",
        "to_detail": "谢谢您的分享，接下来我想再了解一些您的家庭和生活情况。",
        "to_ready": "太好了，我对您有了初步的了解。现在让我们开始讲述您的故事吧！",
    }