import type { Chapter, DemoState, FeedItem, MatchMock, Seat } from '../model/types'

// 设计稿 mock：标准 12 人局（预女猎守 + 狼王）与极简 6 人局
function seats(defs: Array<[number, string, string, string, string, Seat['role']]>): Seat[] {
  const half = Math.ceil(defs.length / 2)
  return defs.map(([id, name, persona, model, emoji, role], i) => ({
    id,
    name,
    persona,
    model,
    emoji,
    role,
    team: role === 'wolf' || role === 'wolf_king' ? 'wolf' : 'good',
    alive: true,
    side: i < half ? 'L' : 'R',
  }))
}

const standard12: Seat[] = seats([
  [1, '林间狐', '悍跳强攻型', 'qwen-max', '🦊', 'wolf_king'],
  [2, '夜枭', '冷静盘逻辑型', 'deepseek-v3', '🦉', 'seer'],
  [3, '老好人', '真诚朴实型', 'glm-4', '🐻', 'villager'],
  [4, '沉默刀客', '寡言观察型', 'qwen-max', '🐱', 'wolf'],
  [5, '戏精上校', '表演型人格', 'doubao-pro', '🦁', 'villager'],
  [6, '白月光', '温柔和善型', 'glm-4', '🐰', 'guard'],
  [7, '数学家', '概率狂魔', 'deepseek-v3', '🐢', 'witch'],
  [8, '大嗓门', '激情演讲型', 'doubao-pro', '🐮', 'hunter'],
  [9, '老阴币', '阴阳怪气型', 'qwen-max', '🐙', 'wolf'],
  [10, '小学生', '直球选手', 'glm-4', '🐧', 'villager'],
  [11, '奶妈', '照顾全场型', 'deepseek-v3', '🦔', 'villager'],
  [12, '裁判长', '一本正经型', 'doubao-pro', '🐝', 'wolf'],
])

const ch = (
  label: string,
  apply: (s: DemoState) => void,
): Chapter => ({ label, apply })

const feed = (kind: FeedItem['kind'], seat: number | undefined, text: string, monologue?: string): FeedItem => ({
  kind,
  seat,
  text,
  monologue,
})

const standardChapters: Chapter[] = [
  ch('第 1 夜 · 狼队密谋', (s) => {
    s.phase = 'night'
    s.day = 1
    s.feed.push(
      feed('system', undefined, '🌙 天黑请闭眼……狼人请睁眼。'),
      feed('channel', 1, '都别跳，今晚刀 2 号，那个猫头鹰讲话太有条理了。', '2号大概率预言家，开局带走最稳。'),
      feed('channel', 4, '同意。但我建议明天我装好人，你们仨分头打。', '我要攒人设，后天再捞。'),
      feed('channel', 9, '行，那我就负责搅水，谁蹦跶我踩谁~', '嘿嘿，这局我演个热心好人。'),
      feed('channel', 12, '没有异议。散会。', '如无意外，跟刀即可。'),
      feed('system', undefined, '🔪 狼人们达成了一致（上帝视角可见，观众沉浸视角不可见）'),
    )
    s.deadSeats = [2]
  }),
  ch('第 1 天 · 死讯与警长竞选', (s) => {
    s.phase = 'day'
    s.feed.push(
      feed('system', undefined, '☀️ 天亮了——昨夜，2 号「夜枭」出局。'),
      feed('system', undefined, '🏅 警长竞选：1、5、7 号上警。'),
      feed('speech', 1, '我上警！我是来给大家当主心骨的，信我，票跟我走。', '狼王起跳预言家，抢警徽撕好人节奏。'),
      feed('speech', 5, '咳咳——本上校从不写真话，但我今天例外：我真是预言家！', '我不是预言家，但气势必须拉满。'),
      feed('speech', 7, '按贝叶斯分析，上警三人中至少一狼。我查杀节奏请大家记录在案。', '我真是女巫，不能跳，只能打逻辑。'),
    )
    s.sheriff = 5
    s.vote = {
      day: 1,
      title: '警长投票',
      tally: { 1: 3, 5: 4, 7: 2 },
    }
  }),
  ch('第 1 天 · 轮流发言', (s) => {
    s.phase = 'day'
    s.vote = null
    s.sheriff = 5
    s.feed.push(
      feed('system', undefined, '🏅 5 号「戏精上校」当选警长，决定逆时针发言。'),
      feed('speech', 3, '我昨晚睡得特别香，什么都没听见。我就一条：谁急谁狼。', '1号喊得最响，先记一笔。'),
      feed('speech', 9, '3号同学太可爱了~ 不过 5 号警长跳得这么坚决，我先跟警长走哦~', '稳住，抱好人小腿。'),
      feed('speech', 7, '1 号的发言全是口号没有信息。警徽在狼手里，这局会很难打。', '1 号悍跳，9 号在带票。'),
      feed('speech', 12, '我反对 7 号的发言方式，扣帽子式推理对局没有任何帮助。', '女巫已死，压力不大。'),
    )
  }),
  ch('第 1 天 · 放逐投票', (s) => {
    s.phase = 'day'
    s.feed.push(feed('system', undefined, '🗳️ 请各位投票放逐一名玩家（警长 2 票）。'))
    s.vote = {
      day: 1,
      title: '放逐投票',
      tally: { 1: 4, 7: 5, 12: 2, 9: 1, 5: 2 },
      exile: 7,
    }
    s.feed.push(
      feed('system', undefined, '⚖️ 7 号「数学家」被放逐出局。'),
      feed('last_words', 7, '各位，我是女巫。解药还没用。1 号悍跳、9 号跟风，这两张牌至少一狼。别浪费我的药。', '可惜，真相只能带进坟墓一半。'),
    )
    s.deadSeats = [2, 7]
  }),
  ch('第 2 夜 · 风暴前夜', (s) => {
    s.phase = 'night'
    s.day = 2
    s.vote = null
    s.feed.push(
      feed('system', undefined, '🌙 第 2 夜降临。狼人请睁眼。'),
      feed('channel', 1, '警徽在手，明天我直接发金水给 9 号。', '警长身份太好用。'),
      feed('channel', 9, '懂了，我哭得惨一点。', '影帝上线。'),
      feed('channel', 12, '今晚刀 8 号，猎人必须死。', '按剧本走。'),
    )
    s.deadSeats = [2, 7]
  }),
]

const minimal6: Seat[] = seats([
  [1, '阿汪', '莽撞冲锋型', 'qwen-max', '🐶', 'wolf'],
  [2, '阿喵', '优雅腹黑型', 'deepseek-v3', '😺', 'seer'],
  [3, '阿猪', '躺平乐观型', 'glm-4', '🐷', 'villager'],
  [4, '阿兔', '胆小谨慎型', 'glm-4', '🐰', 'villager'],
  [5, '阿狼', '老谋深算型', 'qwen-max', '🐺', 'wolf'],
  [6, '阿雀', '叽叽喳喳型', 'deepseek-v3', '🐦', 'villager'],
])

const minimalChapters: Chapter[] = [
  ch('第 1 夜 · 狼队密谋', (s) => {
    s.phase = 'night'
    s.day = 1
    s.feed.push(
      feed('system', undefined, '🌙 天黑请闭眼……'),
      feed('channel', 1, '刀 6！她话最多。', '话痨先死，江湖规矩。'),
      feed('channel', 5, '可以，但明天都别抢跳。', '稳住就能赢。'),
    )
    s.deadSeats = [6]
  }),
  ch('第 1 天 · 发言与投票', (s) => {
    s.phase = 'day'
    s.feed.push(
      feed('system', undefined, '☀️ 昨夜，6 号「阿雀」出局。'),
      feed('speech', 2, '我预言家，昨晚验了 5 号——狼人。', '真预言家起跳。'),
      feed('speech', 5, '巧了，我也是预言家，我验的是 2 号：狼人。', '对跳，赌记忆。'),
      feed('speech', 3, '两个预言家……那我先信长得可爱的那个。', '完了，我根本听不懂。'),
    )
    s.vote = { day: 1, title: '放逐投票', tally: { 2: 2, 5: 2 }, exile: undefined }
  }),
  ch('第 1 天 · 平安日', (s) => {
    s.phase = 'day'
    s.feed.push(feed('system', undefined, '🕊️ 平票 —— 平安日，无人出局。'))
  }),
  ch('第 2 夜', (s) => {
    s.phase = 'night'
    s.day = 2
    s.feed.push(feed('system', undefined, '🌙 第 2 夜降临。'))
  }),
]

function buildMatch(m: Omit<MatchMock, 'build'>): MatchMock {
  return {
    ...m,
    build(idx: number): DemoState {
      const base: DemoState = {
        phase: 'night',
        day: 1,
        label: m.chapters[idx]?.label ?? '',
        feed: [],
        sheriff: null,
        vote: null,
        deadSeats: [],
      }
      for (let i = 0; i <= Math.min(idx, m.chapters.length - 1); i++) m.chapters[i].apply(base)
      base.label = m.chapters[Math.min(idx, m.chapters.length - 1)].label
      return base
    },
  }
}

export const MATCHES: MatchMock[] = [
  buildMatch({ id: 'ww12', mode: 'werewolf-std', name: '狼人杀 · 标准 12 人局', seats: standard12, chapters: standardChapters }),
  buildMatch({ id: 'ww6', mode: 'werewolf-min', name: '狼人杀 · 极简 6 人局', seats: minimal6, chapters: minimalChapters }),
]

export const LOCKED_GAMES = [
  { name: '谁是卧底', hint: '插件开发中' },
  { name: '阿瓦隆', hint: '排队中' },
]
