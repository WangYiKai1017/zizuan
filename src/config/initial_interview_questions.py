"""Static guided questions for the first interview pass.

MVP keeps this list in code. The flow tracks progress by question id and asks
these items in order before switching to the free interview mode.
"""

INITIAL_INTERVIEW_QUESTIONS = [
    {
        "id": "childhood_home",
        "stage": "童年与少年时光",
        "question": "您小时候住的房子是什么样子的？推开窗户能看到什么风景？",
    },
    {
        "id": "childhood_parents",
        "stage": "童年与少年时光",
        "question": "您的父母在您小时候是什么性格？他们最常挂在嘴边叮嘱您的一句话是什么？",
    },
    {
        "id": "school_corner",
        "stage": "求学与青春岁月",
        "question": "学校里有没有哪个角落承载了您最多的回忆？",
    },
    {
        "id": "youth_career_dream",
        "stage": "求学与青春岁月",
        "question": "年轻时您曾有过什么样的职业梦想？后来实现了吗？",
    },
    {
        "id": "first_salary",
        "stage": "成年奋斗与职业生涯",
        "question": "拿到第一份工资时，您买了什么东西？是给父母买了礼物还是奖励了自己？",
    },
    {
        "id": "career_achievement",
        "stage": "成年奋斗与职业生涯",
        "question": "在您的职业生涯中，哪一个项目或任务让您觉得最有成就感？",
    },
    {
        "id": "meeting_partner",
        "stage": "婚姻家庭与亲情羁绊",
        "question": "您和伴侣是怎么认识的？是经人介绍还是自由恋爱？",
    },
    {
        "id": "becoming_parent",
        "stage": "婚姻家庭与亲情羁绊",
        "question": "得知自己即将成为父母的那一刻，您的第一反应是什么？",
    },
    {
        "id": "retirement_adaptation",
        "stage": "岁月沉淀与生命感悟",
        "question": "刚退休的那段时间，您适应吗？有没有感到失落，又是如何找到新的乐趣的？",
    },
    {
        "id": "life_luck_regret",
        "stage": "岁月沉淀与生命感悟",
        "question": "回顾这一生，您觉得最幸运的一件事是什么？最大的遗憾又是什么？",
    },
]
