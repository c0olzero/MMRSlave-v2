// English and Vietnamese. Keys are the English text; {name} marks a value filled in at run time.
// Hero names and game terms (GPM, net worth, last hits, denies, TP, Roshan, rune, lanes...) stay
// in English in both languages: every Dota 2 player already knows them.

let lang = "en";
try { if (JSON.parse(localStorage.getItem("mmrslave-lang")) === "vi") lang = "vi"; } catch (e) { /* storage blocked */ }
document.documentElement.lang = lang;

export const getLang = () => lang;

export function setLang(next) {
  lang = next === "vi" ? "vi" : "en";
  document.documentElement.lang = lang;
  try { localStorage.setItem("mmrslave-lang", JSON.stringify(lang)); } catch (e) { /* storage blocked */ }
}

export function t(en, vars) {
  let s = (lang === "vi" && VI[en]) || en;
  if (vars) s = s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] ?? ""));
  return s;
}

// A text the server already wrote in both languages ({..., vi: {...}}).
export function loc(obj, key) {
  return lang === "vi" && obj?.vi?.[key] != null ? obj.vi[key] : obj?.[key];
}

export const area = (en) => (lang === "vi" && AREAS[en]) || en;

export function tag(en) {
  if (lang !== "vi") return en;
  const tp = /^teleported in (\d+)s before dying$/.exec(en);
  if (tp) return `TP tới ${tp[1]}s trước khi chết`;
  return TAGS[en] || en;
}

export const statLabel = (key, en) => (lang === "vi" && STATS[key]) || en;

export const dateLocale = () => (lang === "vi" ? "vi-VN" : undefined);

const AREAS = {
  "your base": "base của bạn",
  "the enemy base": "base địch",
  "mid lane": "đường mid",
  "the river": "sông",
  "your safe lane": "safe lane của bạn",
  "your off lane": "off lane của bạn",
  "your safe-lane jungle": "rừng safe lane của bạn",
  "your off-lane jungle": "rừng off lane của bạn",
  "the enemy safe-lane jungle": "rừng safe lane của địch",
  "the enemy off-lane jungle": "rừng off lane của địch",
};

const TAGS = {
  "caught alone, outnumbered": "bị bắt lẻ, bị đông hơn",
  "outnumbered": "bị đông hơn",
  "several enemies missing and no ward nearby": "nhiều địch mất tích và không có ward gần đó",
  "deep in enemy territory": "lấn sâu vào vùng địch",
  "stayed on low HP": "ở lại khi máu thấp",
  "teleported in a few seconds before dying": "TP tới vài giây trước khi chết",
  "killed by a tower": "bị trụ giết",
  "traded in a fight your team didn't lose": "đổi mạng trong giao tranh đội bạn không thua",
  "lingered in danger": "nán lại nơi nguy hiểm",
  "Immortal players rarely go there in this situation": "người chơi Immortal hiếm khi tới đó trong tình huống này",
};

const STATS = {
  gpm: "GPM", xpm: "XPM",
  deaths_per_30: "Death mỗi 30 phút", ka_per_30: "Kill + assist mỗi 30 phút",
  dead_pct: "% thời gian nằm chết", hero_damage_per_min: "Hero damage mỗi phút",
  tower_damage_per_min: "Tower damage mỗi phút", obs_per_30: "Observer ward mỗi 30 phút",
  sen_per_30: "Sentry ward mỗi 30 phút", fight_participation: "Tham gia giao tranh",
  wards_killed_per_30: "Ward địch bị phá mỗi 30 phút",
};

const VI = {
  // shell
  "Skip to the review": "Bỏ qua, tới phần đánh giá",
  "Your games": "Trận của bạn",
  "Fetch my latest games": "Tải các trận mới nhất",
  "Coach brain": "Bộ não HLV",
  "checking…": "đang kiểm tra…",
  "Loading your games…": "Đang tải trận của bạn…",
  "Switch to dark mode": "Chuyển sang giao diện tối",
  "Switch to light mode": "Chuyển sang giao diện sáng",
  "Language": "Ngôn ngữ",
  "No games yet. Fetch your latest games to start.": "Chưa có trận nào. Hãy tải các trận mới nhất để bắt đầu.",
  "not reviewed yet": "chưa đánh giá",
  "Today": "Hôm nay",
  "Yesterday": "Hôm qua",
  "{n} days ago": "{n} ngày trước",
  "{games} Immortal games learned": "Đã học {games} trận Immortal",
  " · win chance {p}% right": " · đoán thắng đúng {p}%",
  "Couldn't load your games: {e}": "Không tải được trận của bạn: {e}",
  "Asking OpenDota for your recent games…": "Đang hỏi OpenDota các trận gần đây của bạn…",
  "Fetching failed.": "Tải thất bại.",
  "Couldn't fetch: {e}": "Không tải được: {e}",
  "Up to date.": "Đã cập nhật.",
  "No games to review yet": "Chưa có trận nào để đánh giá",
  "Press <b>{btn}</b> to download your last 20 ranked games. In Dota 2, keep <b>Settings → Social → Expose Public Match Data</b> on, or they can't be found.":
    "Bấm <b>{btn}</b> để tải 20 trận ranked gần nhất. Trong Dota 2, hãy bật <b>Settings → Social → Expose Public Match Data</b>, nếu không sẽ không tìm thấy trận.",
  "From a terminal you can also run <code>python -m mmrslave mine</code>.": "Bạn cũng có thể chạy <code>python -m mmrslave mine</code> trong terminal.",

  // opening a game
  "Reviewing this game… (the first look takes a few seconds)": "Đang đánh giá trận này… (lần đầu mất vài giây)",
  "Couldn't open this game": "Không mở được trận này",
  "Try again": "Thử lại",
  "You're not in this game": "Bạn không có trong trận này",
  "Check <code>player.steam_id</code> in mmrslave.toml.": "Kiểm tra <code>player.steam_id</code> trong mmrslave.toml.",

  // header
  "Result": "Kết quả",
  "Won": "Thắng",
  "Lost": "Thua",
  "Position": "Vị trí",
  "Duration": "Thời lượng",
  "Side": "Phe",
  "Match": "Trận",
  "Re-run review": "Đánh giá lại",
  "Reviewing the game again…": "Đang đánh giá lại trận…",
  "Couldn't re-run the review: {e}": "Không đánh giá lại được: {e}",

  // verdict
  "{result} in {dur}. The moment to fix first: {clock}, {title}.": "{result} sau {dur}. Khoảnh khắc cần sửa trước tiên: {clock}, {title}.",
  "{result} in {dur} as {hero}.": "{result} sau {dur} với {hero}.",
  "The written review isn't here yet. Press <b>Re-run review</b> to write it.": "Chưa có bài đánh giá viết. Bấm <b>Đánh giá lại</b> để tạo.",
  "Written coaching is off. Set the <code>ANTHROPIC_API_KEY</code> environment variable and restart the dashboard to get a full review in plain words; the findings below work without it.":
    "Coaching dạng văn bản đang tắt. Đặt biến môi trường <code>ANTHROPIC_API_KEY</code> và khởi động lại dashboard để có bài đánh giá đầy đủ; các phát hiện bên dưới vẫn hoạt động mà không cần nó.",
  "The written review is in English.": "Bài đánh giá viết bằng tiếng Anh.",

  // moments
  "Your death": "Bạn chết",
  "Fight you missed": "Giao tranh bị lỡ",
  "Tower lost": "Mất trụ",
  "No objective": "Không lấy mục tiêu",
  "Runes": "Rune",
  "Coach": "Coach",
  "Died to {killer} in {where}": "Bị {killer} hạ ở {where}",
  "Why it mattered:": "Vì sao quan trọng:",
  "Next time:": "Lần sau:",
  "Allies nearby: {list}.": "Đồng đội gần đó: {list}.",
  "No allies nearby.": "Không có đồng đội gần đó.",
  "Enemies on you: {list}.": "Địch đánh bạn: {list}.",
  "Missing from your team's map just before: {list}.": "Biến mất khỏi bản đồ của đội bạn ngay trước đó: {list}.",
  "{n} of your wards covered the spot": "{n} ward của bạn soi chỗ đó",
  "No ward of yours covered the spot": "Không có ward nào của bạn soi chỗ đó",
  "{n} enemy ward saw you": "{n} ward địch thấy bạn",
  "HP 10s before: {p}%.": "HP 10s trước đó: {p}%.",
  "Death risk peaked at <b>{p}%</b> in the 30s before": "Nguy cơ chết cao nhất <b>{p}%</b> trong 30s trước đó",
  ", and you stayed in danger for {s}s": ", và bạn ở trong vùng nguy hiểm {s}s",
  "From where you were 30s earlier, high-Immortal players most often went to <b>{where}</b> ({p}%); they ended up where you died {q}% of the time.":
    "Từ chỗ bạn đứng 30s trước, người chơi high-Immortal thường đi tới <b>{where}</b> nhất ({p}%); họ có mặt ở chỗ bạn chết {q}% số lần.",
  "What you could have done better": "Những gì bạn có thể làm tốt hơn",
  "What you could have done differently": "Những gì bạn có thể làm khác đi",
  "Nothing stood out in this game.": "Trận này không có gì nổi bật.",
  "Keep playing": "Tiếp tục phát",
  "Close": "Đóng",

  // board and player
  "The board": "Bản đồ",
  "The map at the current moment of the game. Hover or focus a hero for details.": "Bản đồ tại thời điểm hiện tại của trận. Rê chuột hoặc chọn một hero để xem chi tiết.",
  "Enemies as your team saw them": "Địch theo tầm nhìn của đội bạn",
  "{s}s before you died at {clock} · enemies as your team saw them": "{s}s trước khi bạn chết lúc {clock} · địch theo tầm nhìn của đội bạn",
  "When you died at {clock} · enemies as your team saw them": "Lúc bạn chết ({clock}) · địch theo tầm nhìn của đội bạn",
  "This replay is from before fog-of-war was recorded, so the board shows every hero.": "Replay này có từ trước khi fog-of-war được ghi lại, nên bản đồ hiện mọi hero.",
  "Radiant gold": "Gold của Radiant",
  "Dire gold": "Gold của Dire",
  "your team": "đội bạn",
  "enemy": "địch",
  "unspent gold": "gold chưa tiêu",
  "net worth": "net worth",
  "(you)": "(bạn)",
  "Playback": "Phát lại",
  "Game time": "Thời gian trận",
  "Back 10 seconds": "Lùi 10 giây",
  "Forward 10 seconds": "Tới 10 giây",
  "Play": "Phát",
  "Pause": "Tạm dừng",
  "Speed": "Tốc độ",
  "Slower": "Chậm hơn",
  "Faster": "Nhanh hơn",
  "Pause at coach moments": "Dừng ở khoảnh khắc coach",

  // hero card
  "Unspent gold": "Gold chưa tiêu",
  "backpack": "túi phụ",
  "dead": "đã chết",
  "Items weren't recorded for this game. <code>python -m mmrslave reparse</code> adds them while Valve still has the replay.":
    "Trận này chưa ghi lại item. <code>python -m mmrslave reparse</code> sẽ bổ sung khi Valve vẫn còn replay.",
  "{hp}% health · {mp}% mana": "{hp}% máu · {mp}% mana",
  " · your team couldn't see them": " · đội bạn không thấy",
  "{g} gold": "{g} gold",

  // win chance
  "Your team's win chance": "Tỉ lệ thắng của đội bạn",
  "Your team's win chance over the game; {r} at {d}": "Tỉ lệ thắng của đội bạn trong trận; {r} lúc {d}",
  "your deaths": "bạn chết",
  "teammates' deaths": "đồng đội chết",
  "enemy deaths": "địch chết",
  "after {clock}: rough, few Immortal games last this long": "sau {clock}: ước lượng thô, ít trận Immortal kéo dài vậy",
  "Click anywhere to jump the board there.": "Bấm vào bất kỳ đâu để đưa bản đồ tới đó.",
  "The win-chance model isn't trained yet: run <code>python -m mmrslave train</code>.": "Mô hình tỉ lệ thắng chưa được huấn luyện: chạy <code>python -m mmrslave train</code>.",

  // tabs
  "More about this game": "Thêm về trận này",
  "vs Immortal": "vs Immortal",
  "Laning & items": "Đi lane & item",
  "Practice plan": "Kế hoạch luyện tập",

  // vs Immortal
  "Loading the Immortal curves…": "Đang tải đường Immortal…",
  "Couldn't load the Immortal curves: {e}": "Không tải được đường Immortal: {e}",
  "same hero and position": "cùng hero và vị trí",
  "same position": "cùng vị trí",
  "same hero": "cùng hero",
  "You against high-Immortal players on the {cmp} ({n} games), minute by minute. The yellow band is the middle half of them; the yellow line is a typical one.":
    "Bạn so với người chơi high-Immortal {cmp} ({n} trận), theo từng phút. Dải vàng là nửa giữa của họ; đường vàng là mức điển hình.",
  "Immortal curves aren't built yet: run <code>python -m mmrslave benchmarks</code>.": "Chưa có đường Immortal: chạy <code>python -m mmrslave benchmarks</code>.",
  "Stat to compare": "Chỉ số để so sánh",
  "General stats": "Chỉ số chung",
  "This game was saved before {stat} over time was recorded. Run <code>python -m mmrslave reparse</code> while Valve still has the replay (about 10 days).":
    "Trận này được lưu trước khi {stat} theo thời gian được ghi lại. Chạy <code>python -m mmrslave reparse</code> khi Valve còn giữ replay (khoảng 10 ngày).",
  "Few Immortal games on this hero have {stats} over time yet, so that line compares you with every Immortal player in your position ({n} games).":
    "Chưa có nhiều trận Immortal của hero này có {stats} theo thời gian, nên đường này so bạn với mọi người chơi Immortal cùng vị trí ({n} trận).",
  "Few Immortal games on this hero have {stats} over time yet, so those lines compare you with every Immortal player in your position ({n} games).":
    "Chưa có nhiều trận Immortal của hero này có {stats} theo thời gian, nên các đường này so bạn với mọi người chơi Immortal cùng vị trí ({n} trận).",
  "Not enough Immortal games with {stats} over time yet ({n} so far). New games are saved with it, so the yellow line appears as the collector runs and after <code>python -m mmrslave benchmarks</code>.":
    "Chưa đủ trận Immortal có {stats} theo thời gian ({n} trận). Các trận mới đều được lưu kèm, nên đường vàng sẽ xuất hiện khi collector chạy và sau khi chạy <code>python -m mmrslave benchmarks</code>.",
  "{label}: you against high-Immortal players, by minute": "{label}: bạn so với người chơi high-Immortal, theo phút",
  "You": "Bạn",
  "middle half of Immortal players": "nửa giữa người chơi Immortal",
  "Show as a table": "Xem dạng bảng",
  "Minute": "Phút",
  "better than {p}%": "tốt hơn {p}%",
  "Immortal typical {v}": "Immortal điển hình {v}",
  "{o} observer and {s} sentry wards placed": "cắm {o} observer và {s} sentry ward",
  "{n} enemy ward destroyed": "phá {n} ward địch",
  "{n} enemy wards destroyed": "phá {n} ward địch",
  "in {p}% of your team's kills": "tham gia {p}% số kill của đội",
  "{n} hero damage": "{n} hero damage",
  "{n} building damage": "{n} building damage",
  "{s}s of stuns": "{s}s stun",
  "{n} camps stacked": "stack {n} bãi quái",
  "This game: {list}.": "Trận này: {list}.",
  "The bar shows how many Immortal players on the {cmp} you did better than; the middle tick is a typical one.":
    "Thanh cho biết bạn tốt hơn bao nhiêu người chơi Immortal {cmp}; vạch giữa là mức điển hình.",
  "Immortal benchmarks aren't built yet, or there aren't enough Immortal games on this hero. Run <code>python -m mmrslave benchmarks</code> after collecting more games.":
    "Chưa có benchmark Immortal, hoặc chưa đủ trận Immortal của hero này. Chạy <code>python -m mmrslave benchmarks</code> sau khi thu thập thêm trận.",

  // laning & items
  "Your lane at 10:00": "Lane của bạn lúc 10:00",
  "Hero": "Hero",
  "enemy pos {p}": "pos {p} địch",
  "{k} kills and {d} deaths before 10:00": "{k} kill và {d} death trước 10:00",
  "The game ended before 10:00.": "Trận kết thúc trước 10:00.",
  "Item timings vs Immortal ({cmp})": "Thời điểm lên item so với Immortal ({cmp})",
  "Typical Immortal": "Immortal điển hình",
  "Difference": "Chênh lệch",
  "{n} min": "{n} phút",
  "Immortal players usually build these on this hero": "Người chơi Immortal thường lên các item này cho hero này",
  "{p}% of Immortal games over 30 minutes, usually by {t}.": "{p}% trận Immortal dài hơn 30 phút, thường xong trước {t}.",

  // practice
  "Patterns in your {n} deaths": "Khuôn mẫu trong {n} lần chết của bạn",
  "{n} of {m}: {tag}": "{n}/{m}: {tag}",
  "Decisions to work on": "Quyết định cần cải thiện",
  "{n} fight you could have reached in time": "{n} giao tranh bạn có thể tới kịp",
  "{n} fights you could have reached in time": "{n} giao tranh bạn có thể tới kịp",
  "Keep an eye on the minimap while farming; when your team commits near a tower you can TP to, go, then farm again.":
    "Để mắt tới minimap khi farm; khi đội bạn lao vào giao tranh gần một trụ bạn TP tới được, hãy đi, rồi farm tiếp.",
  "{n} tower lost while you were away": "Mất {n} trụ khi bạn ở xa",
  "{n} towers lost while you were away": "Mất {n} trụ khi bạn ở xa",
  "Keep a TP scroll and use it when 2+ enemies hit a tower, or push the opposite lane so they have to choose.":
    "Luôn giữ TP scroll và dùng khi 2+ địch đánh trụ, hoặc đẩy lane đối diện để địch phải chọn.",
  "{n} time enemies were dead and nothing was taken": "{n} lần địch chết mà không lấy được gì",
  "{n} times enemies were dead and nothing was taken": "{n} lần địch chết mà không lấy được gì",
  "After a won fight, look at the death timers and walk to the nearest tower or Roshan before farming.":
    "Sau khi thắng giao tranh, xem thời gian hồi sinh của địch và đi đánh trụ gần nhất hoặc Roshan trước khi farm.",
  "The enemy controlled the power runes": "Địch kiểm soát power rune",
  "Check the river rune at the even minutes when your wave is pushed.": "Ghé rune ở sông vào các phút chẵn khi wave của bạn đã đẩy.",
  "Advantages your team used": "Lợi thế đội bạn đã tận dụng",
  "No repeated pattern in your deaths this game.": "Trận này bạn không chết theo khuôn mẫu lặp lại nào.",
  "A practice plan written for this game appears here once written coaching is on (set <code>ANTHROPIC_API_KEY</code>, then press Re-run review).":
    "Kế hoạch luyện tập cho trận này sẽ hiện ở đây khi bật coaching dạng văn bản (đặt <code>ANTHROPIC_API_KEY</code>, rồi bấm Đánh giá lại).",
  "Practise next": "Luyện tập tiếp theo",
  "What you did well": "Những gì bạn làm tốt",

  // coach brain
  "Checking what the coach has learned…": "Đang kiểm tra coach đã học được gì…",
  "Couldn't load the coach's status": "Không tải được trạng thái của coach",
  "Win-chance accuracy as the coach learns": "Độ chính xác dự đoán thắng khi coach học",
  "Win-chance accuracy for each training run": "Độ chính xác dự đoán thắng sau mỗi lần huấn luyện",
  "{n} games": "{n} trận",
  "Accuracy on games the model never saw, after each training run. 50% is a coin flip.":
    "Độ chính xác trên các trận mô hình chưa từng thấy, sau mỗi lần huấn luyện. 50% là tung đồng xu.",
  "Learned from <b class=\"num\">{n}</b> high-Immortal games": "Đã học từ <b class=\"num\">{n}</b> trận high-Immortal",
  " · {n} more queued": " · còn {n} trận chờ",
  " · your games: {n}": " · trận của bạn: {n}",
  "Still early: the coach gets much sharper past a few thousand games.": "Vẫn còn sớm: coach sẽ sắc bén hơn nhiều sau vài nghìn trận.",
  "Trained on enough games to trust the big swings.": "Đã học đủ trận để tin được các biến động lớn.",
  "Valve keeps replays for about 10 days, so new Immortal games are collected continuously and the models are retrained as they arrive. Run <code>python -m mmrslave auto</code> (or leave <code>collect</code> running) to keep it learning.":
    "Valve chỉ giữ replay khoảng 10 ngày, nên trận Immortal mới được thu thập liên tục và mô hình được huấn luyện lại khi có trận mới. Chạy <code>python -m mmrslave auto</code> (hoặc để <code>collect</code> chạy) để coach tiếp tục học.",
  "Win chance": "Tỉ lệ thắng",
  "How often it picks the eventual winner at a random moment of a game it never saw. Used to price every death and find the turning points.":
    "Tần suất đoán đúng đội thắng ở một thời điểm ngẫu nhiên của trận chưa từng thấy. Dùng để tính giá mỗi lần chết và tìm bước ngoặt.",
  "Death risk": "Nguy cơ chết",
  "How well it tells moments right before a death from safe ones (0.5 = guessing, 1.0 = perfect), using only what the hero's team could see.":
    "Khả năng phân biệt khoảnh khắc ngay trước khi chết với lúc an toàn (0.5 = đoán mò, 1.0 = hoàn hảo), chỉ dùng những gì đội của hero thấy được.",
  "Where Immortals go": "Immortal đi đâu",
  "How often the real spot a player reached 30 seconds later is among its five best guesses on the map.":
    "Tần suất vị trí thực tế người chơi tới sau 30 giây nằm trong 5 dự đoán tốt nhất trên bản đồ.",
  "Training runs": "Các lần huấn luyện",
  "When": "Thời điểm",
  "Games": "Trận",
  "No training runs yet. Run <code>python -m mmrslave train</code>.": "Chưa có lần huấn luyện nào. Chạy <code>python -m mmrslave train</code>.",
  "Written coaching: on.": "Coaching dạng văn bản: bật.",
  "Written coaching: off. Set the <code>ANTHROPIC_API_KEY</code> environment variable and restart the dashboard to turn it on.":
    "Coaching dạng văn bản: tắt. Đặt biến môi trường <code>ANTHROPIC_API_KEY</code> và khởi động lại dashboard để bật.",

  // Steam account
  "Settings": "Cài đặt",
  "Steam account": "Tài khoản Steam",
  "Steam ID {id}": "Steam ID {id}",
  "Steam connected": "Đã kết nối Steam",
  "Sign in through Steam": "Đăng nhập bằng Steam",
  "You sign in on Steam's own page. MMRSlave only learns your Steam ID, never your password.":
    "Bạn đăng nhập trên trang của chính Steam. MMRSlave chỉ biết Steam ID của bạn, không bao giờ biết mật khẩu.",
  "Steam sign-in didn't finish: {e}": "Đăng nhập Steam chưa xong: {e}",
  "This sign-in link expired or wasn't started here. Try again.": "Liên kết đăng nhập đã hết hạn hoặc không được mở từ đây. Hãy thử lại.",
  "Steam sign-in was cancelled.": "Đăng nhập Steam đã bị huỷ.",
  "Steam sent the sign-in back to a different address.": "Steam trả kết quả đăng nhập về một địa chỉ khác.",
  "Steam didn't return a Steam ID.": "Steam không trả về Steam ID.",
  "Steam didn't confirm this sign-in.": "Steam không xác nhận lần đăng nhập này.",
  "Disconnect this Steam account? Your downloaded games stay on this PC.":
    "Ngắt kết nối tài khoản Steam này? Các trận đã tải vẫn được giữ trên máy.",
  "Switch account": "Đổi tài khoản",
  "Sign in through Steam to see your games.": "Đăng nhập bằng Steam để xem các trận của bạn.",
  "Disconnect": "Ngắt kết nối",
  "Connect your Steam account": "Kết nối tài khoản Steam",
  "MMRSlave reviews your own ranked games. Sign in through Steam so it can find them; you sign in on Steam's own page and MMRSlave only learns your Steam ID.":
    "MMRSlave đánh giá các trận ranked của chính bạn. Hãy đăng nhập bằng Steam để app tìm được chúng; bạn đăng nhập trên trang của Steam và MMRSlave chỉ biết Steam ID của bạn.",
  "Connect your Steam account so MMRSlave can find your ranked games. You sign in on Steam's own page: MMRSlave only learns your Steam ID, never your password, and can't do anything with your account.":
    "Kết nối tài khoản Steam để MMRSlave tìm được các trận ranked của bạn. Bạn đăng nhập trên trang của Steam: MMRSlave chỉ biết Steam ID, không bao giờ biết mật khẩu và không thể làm gì với tài khoản của bạn.",
  "OpenDota doesn't know this account yet. In Dota 2, turn on <b>Settings → Social → Expose Public Match Data</b>, play a game, then fetch your games.":
    "OpenDota chưa biết tài khoản này. Trong Dota 2, hãy bật <b>Settings → Social → Expose Public Match Data</b>, chơi một trận, rồi tải các trận của bạn.",
  "Your games are found through OpenDota. In Dota 2, keep <b>Settings → Social → Expose Public Match Data</b> on.":
    "Các trận của bạn được tìm qua OpenDota. Trong Dota 2, hãy luôn bật <b>Settings → Social → Expose Public Match Data</b>.",
  "Check which Steam account is connected in <a href=\"#/settings\">Settings</a>.":
    "Kiểm tra tài khoản Steam đang kết nối trong <a href=\"#/settings\">Cài đặt</a>.",
  "Connect your Steam account first (or set player.steam_id in mmrslave.toml).": "Hãy kết nối tài khoản Steam trước.",

  // updates
  "Updates": "Cập nhật",
  "Version": "Phiên bản",
  "Loading settings…": "Đang tải cài đặt…",
  "Check for updates": "Kiểm tra cập nhật",
  "Install updates automatically when MMRSlave starts": "Tự động cài cập nhật khi mở MMRSlave",
  "Updates come from GitHub: only the changed code and the coach's training, a few MB.":
    "Bản cập nhật lấy từ GitHub: chỉ phần code đã đổi và dữ liệu huấn luyện của coach, vài MB.",
  "Running from a Git clone: updating runs <code>git pull</code>.": "Đang chạy từ bản Git clone: cập nhật sẽ chạy <code>git pull</code>.",
  "This copy wasn't installed from GitHub, so it can't update itself.": "Bản này không được cài từ GitHub nên không tự cập nhật được.",
  "New version available": "Có phiên bản mới",
  "Updating…": "Đang cập nhật…",
  "Checking GitHub…": "Đang kiểm tra GitHub…",
  "Checked at {time}.": "Đã kiểm tra lúc {time}.",
  "You have the newest version.": "Bạn đang dùng phiên bản mới nhất.",
  "New version {v} from {date}: {n} changes": "Phiên bản mới {v} ngày {date}: {n} thay đổi",
  "New version {v} from {date}": "Phiên bản mới {v} ngày {date}",
  "Install and restart": "Cài đặt và khởi động lại",
  "Download the new version": "Tải phiên bản mới",
  "This version adds new libraries, so it needs the full download. Unzip it over this copy (your games and settings stay) and open MMRSlave again.":
    "Phiên bản này thêm thư viện mới nên cần tải bản đầy đủ. Giải nén đè lên bản hiện tại (trận và cài đặt của bạn vẫn giữ nguyên) rồi mở lại MMRSlave.",
  "Restarting on the new version…": "Đang khởi động lại với phiên bản mới…",
  "Installing…": "Đang cài đặt…",
  "Downloading the new version from GitHub…": "Đang tải phiên bản mới từ GitHub…",
  "Unpacking…": "Đang giải nén…",
  "Installed. Restarting…": "Đã cài xong. Đang khởi động lại…",
  "Pulling from GitHub…": "Đang kéo code từ GitHub…",
  "Installing new libraries…": "Đang cài thư viện mới…",
  "Already up to date.": "Đã là bản mới nhất.",
  "The update failed: {e}": "Cập nhật thất bại: {e}",
  "GitHub's limit for update checks is used up for this hour. Try again later.":
    "Đã hết lượt kiểm tra cập nhật GitHub cho giờ này. Hãy thử lại sau.",
  "This update adds new libraries, so it needs the full download from the Releases page.":
    "Bản cập nhật này thêm thư viện mới nên cần tải bản đầy đủ từ trang Releases.",
  "This folder has changes that aren't committed; commit or stash them, then update.":
    "Thư mục này có thay đổi chưa commit; hãy commit hoặc stash rồi cập nhật.",
  "The download was damaged. Try again.": "File tải về bị lỗi. Hãy thử lại.",
};
