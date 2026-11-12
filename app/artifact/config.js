// =====================================================================
// 规则和话术。想改提醒节奏、话术、加学校时的默认事项，只改这个文件。
// =====================================================================
window.CFG = {
  product: "申请进度助手",

  // 提醒节奏：截止前第几天提醒家长。过了截止日的事项排在跟进页最上面，用下面 overdue 那组话术。
  chaseDays: [7, 3, 0],
  // 状态：逾期（红）= 过了截止日还没完成；临期（黄）= soonDays 天内到期；待办（绿）= 还没到期。
  soonDays: 7,
  lightRule: "逾期：过了截止日没完成　临期：7 天内到期　待办：还没到期",

  // 话术。每种都有几种说法，系统按事项固定选一种，顾问可以点"换一种说法"，发之前也能直接改字。
  // 写法：像顾问自己在微信上打的字，有服务意识，让家长觉得有人在替他盯着。长短、开头、句式都不一样。
  // 不带署名，不用特殊符号，不说教，不制造焦虑，不要求家长"回复收到"。日期自动写成 11月14号，中英文之间不留空格。
  // 可用的占位：{家长} {学生} {事项} {截止} {天数}（离截止还有几天，自动写成"两天""三天"）；agreeOne 另有 {谁}（"您"或学生称呼）。
  templates: {
    // 只有一件事时用这一组，写成一句话
    agreeOne: [
      "{家长}，近期有一件事需要留意：{截止}前，{谁}{事项}。我会一直跟着，您放心。",
      "{家长}您好，跟您同步一下：{谁}需要在{截止}前{事项}。过程中有任何不清楚的，随时找我。",
      "{家长}好，{截止}前{谁}要{事项}。到时候我会提前提醒，不用您一直惦记。",
      "辛苦{家长}留意一下，{谁}{事项}这件事，时间是{截止}前。需要我协助的地方您尽管说。"
    ],
    // 两件事以上用这一组，列成清单
    agree: [
      "{家长}，{学生}接下来的安排我帮您整理好了：\n{列表}\n每一项快到时间我都会提前提醒，不用您一直惦记。",
      "{家长}您好，这是{学生}近期的安排，您先过目：\n{列表}\n哪个时间不方便，告诉我，我来协调。",
      "辛苦{家长}看一下{学生}后面的时间表：\n{列表}\n过程中有任何不清楚的，随时找我。",
      "{家长}好，需要家里配合的几件事在这里：\n{列表}\n其余的交给我来跟，您放心。"
    ],
    chase: [
      [ // 截止前 7 天
        "{家长}，{学生}有件事需要您帮忙：{事项}，{截止}之前完成就可以。操作上需要我带着做的话，随时叫我。",
        "{家长}您好，{事项}这件事麻烦您记一下，时间是{截止}前。有不清楚的地方我来说明。",
        "辛苦{家长}，方便的时候处理一下：{事项}。{截止}截止，时间还充裕。",
        "{家长}好，跟您说件事。{事项}需要在{截止}前完成，您看哪天方便？我可以配合您的时间。",
        "{家长}您好，{学生}的申请里有一项需要家里来办：{事项}，截止是{截止}。办的时候遇到问题直接找我，我陪您弄。"
      ],
      [ // 截止前 3 天
        "{家长}，打扰一下，{事项}这件事{截止}截止，还有{天数}。您这两天方便处理吗？需要的话我一步步带您操作。",
        "{家长}您好，{截止}快到了，{事项}还没完成。是不是哪一步不太顺？告诉我，我来帮您看。",
        "辛苦{家长}，再提醒一次：{事项}，还剩{天数}。您这边要是忙，告诉我哪里能替您分担。",
        "{家长}好，{学生}这边其他都在推进，就差这一项：{事项}。{截止}前办好就行，辛苦您了。",
        "{家长}，{事项}的时间是{截止}，只剩{天数}了。您看哪个时间合适，我随时在。"
      ],
      [ // 截止当天
        "{家长}，不好意思今天又来打扰，{事项}今天截止。麻烦您抽空办一下，办好跟我说一声，我马上确认。",
        "{家长}您好，今天是最后一天：{事项}。有任何问题现在就找我，我一直在线。",
        "辛苦{家长}，{事项}需要今天完成，这样{学生}后面的申请才不受影响。我在这边等您消息。",
        "{家长}，今天要把这件事办好：{事项}。如果今天确实不方便，请马上告诉我，我们一起想办法。",
        "{家长}好，{事项}就差今天了。需要我陪着一步步操作，随时叫我。"
      ]
    ],
    // 已经过了截止日、还在等家长或学生的事项，用这一组。语气是帮忙想办法，不是追责。
    overdue: [
      "{家长}，{事项}这件事原定{截止}前完成，现在已经过了。您别着急，我先去确认还能不能补办，您这边方便的话今天抽空处理一下，需要我陪着操作随时叫我。",
      "{家长}您好，{事项}这件事已经过了{截止}。我这边正在帮{学生}看补救的办法，麻烦您尽快处理，哪一步卡住了直接告诉我。",
      "辛苦{家长}，{事项}还没有完成，时间是{截止}，已经过了。是不是最近太忙了？您告诉我哪里不方便，我来想办法配合。",
      "{家长}好，跟您说一下{学生}这边的情况：{事项}超过了原定的{截止}。越早补上对申请越有利，今天您看什么时间合适，我全程在。",
      "{家长}，打扰了。{事项}原本{截止}截止，目前还差这一步。我已经在跟进后续安排，您这边处理好以后告诉我，我马上接着办。"
    ],
    progressOpen: [
      "{家长}，{学生}现在的情况是这样：",
      "{家长}您好，跟您说下{学生}的申请进度。",
      "{学生}这边的进展我汇总了一下，{家长}您看看：",
      "{家长}好，{学生}的申请目前走到这里："
    ],
    progressClose: [
      "有新情况我第一时间告诉您。",
      "后面每件事快到期我都会提前找您，您放心。",
      "想了解哪所学校的细节，随时问我。",
      "整体都在计划内，辛苦您一直配合。"
    ]
  },

  redline: "文书内容由学生自己完成。系统只记录“交了没有、哪天交的”，不改、不写、不翻译。",

  // 加一所学校时默认生成的事项。days = 学校截止日前多少天。
  // 顾问每一条都能改日期、改负责人、取消勾选，也能再加一条。
  backplan: [
    { what: "交 {学校} 文书终稿", owner: "学生", days: 14 },
    { what: "{学校} 送分（语言、标化）", owner: "机构", days: 14 },
    { what: "确认 {学校} 成绩单已提交", owner: "学校", days: 7 },
    { what: "确认 {学校} 推荐信已上传", owner: "学校", days: 7 },
    { what: "付 {学校} 申请费", owner: "家长", days: 5 },
    { what: "递交 {学校} 申请（{轮次}）", owner: "机构", days: 3 }
  ],

  // 学校的中文名和简称。顾问输入这些也能搜到学校。左边必须和日期库里的学校名一字不差。
  aliases: {
    "Harvard University": ["哈佛", "哈佛大学"],
    "Princeton University": ["普林斯顿", "普林斯顿大学"],
    "Columbia University": ["哥大", "哥伦比亚大学"],
    "University of Pennsylvania": ["宾大", "宾夕法尼亚大学", "UPenn", "Penn"],
    "Brown University": ["布朗", "布朗大学"],
    "Dartmouth College": ["达特茅斯", "达特茅斯学院"],
    "Cornell University": ["康奈尔", "康奈尔大学"],
    "Stanford University": ["斯坦福", "斯坦福大学"],
    "California Institute of Technology (Caltech)": ["加州理工", "Caltech"],
    "University of Chicago": ["芝大", "芝加哥大学", "UChicago"],
    "Duke University": ["杜克", "杜克大学"],
    "Johns Hopkins University": ["约翰霍普金斯", "霍普金斯", "JHU"],
    "Northwestern University": ["西北大学", "西北"],
    "Vanderbilt University": ["范德堡", "范德比尔特", "Vandy"],
    "Rice University": ["莱斯", "莱斯大学"],
    "Washington University in St. Louis": ["圣路易斯华盛顿大学", "华大", "WashU", "WUSTL"],
    "University of Notre Dame": ["圣母大学", "圣母"],
    "Emory University": ["埃默里", "埃默里大学"],
    "Georgetown University": ["乔治城", "乔治城大学"],
    "Carnegie Mellon University": ["卡内基梅隆", "卡梅", "CMU"],
    "University of Michigan": ["密歇根大学", "密歇根", "安娜堡", "UMich"],
    "University of Virginia": ["弗吉尼亚大学", "UVA"],
    "University of North Carolina at Chapel Hill": ["北卡教堂山", "北卡", "UNC"],
    "New York University": ["纽约大学", "纽大", "NYU"],
    "University of Southern California": ["南加大", "南加州大学", "USC"],
    "Tufts University": ["塔夫茨", "塔夫茨大学"],
    "Boston University": ["波士顿大学", "波大", "BU"],
    "Boston College": ["波士顿学院", "BC"],
    "Northeastern University": ["东北大学", "NEU"],
    "University of Rochester": ["罗切斯特大学", "罗切斯特"],
    "Brandeis University": ["布兰迪斯", "布兰迪斯大学"],
    "Case Western Reserve University": ["凯斯西储", "CWRU"],
    "Wake Forest University": ["维克森林", "维克森林大学"],
    "Tulane University": ["杜兰", "杜兰大学"],
    "Lehigh University": ["里海", "里海大学"],
    "University of Wisconsin- Madison": ["威斯康星大学麦迪逊", "威斯康星", "麦迪逊", "UW Madison"],
    "University of Illinois Urbana-Champaign": ["伊利诺伊大学香槟", "香槟", "UIUC"],
    "Georgia Institute of Technology": ["佐治亚理工", "Georgia Tech", "GT"],
    "University of Florida": ["佛罗里达大学", "UF"],
    "The University of Texas at Austin": ["德州大学奥斯汀", "奥斯汀", "UT Austin"],
    "University of Washington": ["华盛顿大学", "华大西雅图", "UW"],
    "Purdue University": ["普渡", "普渡大学"],
    "The Ohio State University": ["俄亥俄州立", "OSU"],
    "Penn State": ["宾州州立", "宾州州立大学", "PSU"],
    "University of Maryland": ["马里兰大学", "UMD"],
    "University of Minnesota Twin Cities": ["明尼苏达大学", "UMN"],
    "Rutgers University": ["罗格斯", "罗格斯大学"],
    "University of Pittsburgh": ["匹兹堡大学", "匹大", "Pitt"],
    "Syracuse University": ["雪城", "雪城大学"],
    "The George Washington University": ["乔治华盛顿大学", "GWU"],
    "Fordham University": ["福特汉姆", "福坦莫"],
    "Williams College": ["威廉姆斯", "威廉姆斯学院"],
    "Amherst College": ["阿默斯特", "阿默斯特学院"],
    "Swarthmore College": ["斯沃斯莫尔"],
    "Pomona College": ["波莫纳"],
    "Wellesley College": ["韦尔斯利", "卫斯理"],
    "Indiana University Bloomington - Flagship Campus": ["印第安纳大学"],
    "Michigan State University": ["密歇根州立", "MSU"],
    "University of Miami": ["迈阿密大学"],
    "University of Oxford": ["牛津", "牛津大学"],
    "University of Cambridge": ["剑桥", "剑桥大学"],
    "Imperial College London": ["帝国理工", "帝国理工学院", "IC"],
    "UCL": ["伦敦大学学院", "University College London"],
    "LSE": ["伦敦政经", "伦敦政治经济学院"],
    "King's College London": ["伦敦国王学院", "国王学院", "KCL"],
    "University of Edinburgh": ["爱丁堡", "爱丁堡大学"],
    "University of Manchester": ["曼彻斯特", "曼大", "曼彻斯特大学"],
    "University of Bristol": ["布里斯托", "布里斯托大学"],
    "University of Warwick": ["华威", "华威大学"],
    "University of Melbourne": ["墨尔本大学", "墨大"],
    "University of Sydney": ["悉尼大学", "悉大", "USYD"],
    "UNSW Sydney": ["新南威尔士大学", "新南", "UNSW"],
    "Australian National University": ["澳国立", "澳洲国立大学", "ANU"],
    "Monash University": ["莫纳什", "蒙纳士", "莫纳什大学"],
    "University of Queensland": ["昆士兰大学", "昆大", "UQ"],
    "University of Western Australia": ["西澳大学", "西澳", "UWA"],
    "Adelaide University": ["阿德莱德大学", "阿大"],
    "香港大学 HKU": ["港大", "HKU"],
    "香港中文大学 CUHK": ["港中文", "中大", "CUHK"],
    "香港科技大学 HKUST": ["港科大", "科大", "HKUST"],
    "香港理工大学 PolyU": ["港理工", "理大", "PolyU"],
    "香港城市大学 CityU": ["港城大", "城大", "CityU"],
    "香港浸会大学 HKBU": ["浸会", "浸大", "HKBU"],
    "岭南大学 Lingnan": ["岭南", "岭大"],
    "香港教育大学 EdUHK": ["教大", "港教大", "EdUHK"]
  },

  roundOptions: ["ED", "ED II", "EA", "REA", "RD", "第一批", "主批", "最终批", "第一学期", "第二学期", "滚动录取"]
};
