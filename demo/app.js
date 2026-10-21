/* ==========================================================================
   麦麦瘦身助手 · 演示交互
   数据：data.js（由 demo/build_demo_data.py 生成）
   评分公式与 src/mcd_fit/advisor.py 保持一致
   ========================================================================== */
(function () {
  "use strict";

  const D = window.MCD_DEMO;
  if (!D) return;

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
  const money = (fen) => "¥" + (fen / 100).toFixed(2);
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const fmtInt = (n) => Math.round(n).toLocaleString("zh-CN");

  const ACT = {
    sedentary: { f: 1.2, label: "久坐" },
    light: { f: 1.375, label: "轻度活动" },
    moderate: { f: 1.55, label: "中度活动" },
    active: { f: 1.725, label: "高强度" },
  };
  const FLOOR = { M: 1500, F: 1200 };
  const MEAL_SODIUM_LIMIT = 700;
  const MEAL_SUGAR_LIMIT = 17;

  /* ---------------- 状态 ---------------- */
  const state = {
    sex: D.user.sex,
    age: D.user.age,
    height: D.user.heightCm,
    weight: D.user.weightKg,
    activity: D.user.activity,
    month: "2026-09",
    filter: "全部",
    planIndex: 0,
    takeway: "eat-in",
    scanned: false,
  };

  let target = { bmr: 0, tdee: 0, daily: 0, meal: 0, bmi: 0, label: "" };
  let plans = [];

  const imgByCode = {};
  D.menu.forEach((m) => (imgByCode[m.code] = m.image));

  // 与 MCP calculate-price 复核过的那一单（顺序不敏感）
  const PRICED_CODES = ["5022", "4825", "4437", "507411"].sort();

  /* ---------------- 01 目标计算 ---------------- */
  function computeTarget() {
    const base = 10 * state.weight + 6.25 * state.height - 5 * state.age;
    const bmr = base + (state.sex === "M" ? 5 : -161);
    const tdee = bmr * (ACT[state.activity] || ACT.light).f;
    const floor = FLOOR[state.sex] || 1500;
    const daily = Math.max(tdee - 400, floor);
    const h = state.height / 100;
    const bmi = state.weight / (h * h);
    const label = bmi < 18.5 ? "偏瘦" : bmi < 24 ? "正常" : bmi < 28 ? "超重" : "肥胖";
    target = {
      bmr: Math.round(bmr),
      tdee: Math.round(tdee),
      daily: daily,
      meal: daily / 3,
      bmi: bmi.toFixed(1),
      label,
    };
    return target;
  }

  function paintTarget(animate) {
    $("#tBmr").textContent = fmtInt(target.bmr);
    $("#tTdee").textContent = fmtInt(target.tdee);
    $("#tDaily").textContent = fmtInt(target.daily);
    $("#tMeal").textContent = fmtInt(target.meal);
    $("#tDeficit").textContent = state.sex === "F" ? "−400" : "−400";
    $("#tBmi").textContent = target.bmi + " · " + target.label;
    $("#sideMeal").textContent = fmtInt(target.meal);
    $("#heroCalSub").textContent = "每日目标 " + fmtInt(target.daily) + " kcal";

    // 环形图：缺口占 TDEE 的比例
    const pct = clamp(400 / Math.max(target.tdee, 1), 0.05, 0.4);
    const C = 2 * Math.PI * 52;
    const bar = $("#ringBar");
    bar.setAttribute("stroke-dashoffset", animate ? C : C * (1 - pct));
    requestAnimationFrame(() => bar.setAttribute("stroke-dashoffset", C * (1 - pct)));

    const side = $("#sideRing");
    const sidePct = clamp(target.meal / Math.max(target.daily, 1), 0.1, 1);
    side.setAttribute("stroke-dashoffset", C * (1 - sidePct));

    $("#targetFoot").innerHTML =
      "当前按" + (state.sex === "M" ? "男性" : "女性") + "、" + ACT[state.activity].label +
      "估算：TDEE " + fmtInt(target.tdee) + " kcal，减脂缺口 400 kcal，每日目标 " +
      fmtInt(target.daily) + " kcal（不低于安全下限 " + FLOOR[state.sex] + "）。本餐目标取其 1/3。";
  }

  function bindProfile() {
    const range = (id, key, out, pctId) => {
      const el = $("#" + id);
      const paint = () => {
        const p = ((el.value - el.min) / (el.max - el.min)) * 100;
        el.style.setProperty("--pct", p + "%");
        $("#" + out).textContent = el.value;
      };
      el.addEventListener("input", () => {
        state[key] = Number(el.value);
        paint();
        computeTarget();
        paintTarget();
        if (state.scanned) {
          renderKpis();
          renderHabits();
          renderCalendar();
        }
        refreshPlans();
      });
      paint();
    };
    range("age", "age", "ageOut");
    range("height", "height", "heightOut");
    range("weight", "weight", "weightOut");

    $("#activity").addEventListener("change", (e) => {
      state.activity = e.target.value;
      computeTarget();
      paintTarget();
      if (state.scanned) {
        renderKpis();
        renderHabits();
        renderCalendar();
      }
      refreshPlans();
    });

    $$("#sexSeg button").forEach((b) =>
      b.addEventListener("click", () => {
        $$("#sexSeg button").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        state.sex = b.dataset.v;
        computeTarget();
        paintTarget();
        refreshPlans();
      })
    );
  }

  /* ---------------- 评分（与 advisor.py 同公式） ---------------- */
  function scoreOf(plan, tgt) {
    const kcal = plan.kcal;
    const kcalPenalty = -Math.abs(kcal - tgt) * 0.6;
    const proteinBonus = plan.protein * 2;
    const sodiumPenalty = -Math.max(0, plan.sodium - MEAL_SODIUM_LIMIT) * 0.05;
    const sugarPenalty = -Math.max(0, plan.sugar - MEAL_SUGAR_LIMIT) * 1.5;
    const total = kcalPenalty + proteinBonus + sodiumPenalty + sugarPenalty;
    return {
      kcalPenalty: Math.round(kcalPenalty * 10) / 10,
      proteinBonus: Math.round(proteinBonus * 10) / 10,
      sodiumPenalty: Math.round(sodiumPenalty * 10) / 10,
      sugarPenalty: Math.round(sugarPenalty * 10) / 10,
      total: Math.round(total * 10) / 10,
    };
  }

  function reasonsOf(plan, tgt) {
    const r = [];
    const delta = plan.kcal - tgt;
    if (Math.abs(delta) <= tgt * 0.1) {
      r.push("热量 " + fmtInt(plan.kcal) + " kcal，贴合本餐目标 " + fmtInt(tgt) + " kcal。");
    } else if (delta < 0) {
      r.push("热量 " + fmtInt(plan.kcal) + " kcal，低于目标 " + fmtInt(tgt) +
        " kcal（富余 " + fmtInt(-delta) + " kcal），适合搭配其他正餐。");
    } else {
      r.push("热量 " + fmtInt(plan.kcal) + " kcal，超出目标 " + fmtInt(delta) + " kcal，仅建议偶尔。");
    }
    const ratio = plan.kcal ? Math.round((plan.protein * 4 / plan.kcal) * 100) : 0;
    r.push("蛋白质 " + fmtInt(plan.protein) + " g（供能比 " + ratio + "%），饱腹感更强。");
    if (plan.sodium > MEAL_SODIUM_LIMIT) {
      r.push("钠 " + fmtInt(plan.sodium) + " mg，超过单餐参考上限 " + MEAL_SODIUM_LIMIT + " mg，建议当日清淡。");
    }
    if (plan.sugar > MEAL_SUGAR_LIMIT) {
      r.push("糖 " + fmtInt(plan.sugar) + " g，超过单餐参考上限 " + MEAL_SUGAR_LIMIT + " g。");
    }
    if (plan.discountFen > 0) {
      r.push("已比价：用「" + plan.coupons.join("、") + "」，" +
        money(plan.subtotalFen) + " → " + money(plan.totalFen) + "。");
    } else {
      r.push("实付 " + money(plan.totalFen) + "。");
    }
    return r;
  }

  function rebuildPlans() {
    const tgt = target.meal;
    const scored = D.candidates
      .map((p) => {
        const s = scoreOf(p, tgt);
        return Object.assign({}, p, { score: s.total, breakdown: s, reasons: reasonsOf(p, tgt) });
      })
      .sort((a, b) => b.score - a.score);

    const tiers = [];
    if (scored.length) {
      tiers.push({ plan: scored[0], label: "最贴合目标" });
      const head = scored.slice(0, 6).filter((p) => p.items.length >= 3);
      if (head.length) {
        const cheap = head.reduce((a, b) => (b.totalFen < a.totalFen ? b : a));
        if (cheap.items !== tiers[0].plan.items) tiers.push({ plan: cheap, label: "最省钱" });
      }
      const lightPool = scored.slice(0, 8).filter((p) => p.items.length >= 3);
      if (lightPool.length) {
        const light = lightPool.reduce((a, b) => (b.kcal < a.kcal ? b : a));
        if (tiers.every((t) => t.plan.items !== light.items)) tiers.push({ plan: light, label: "最低热量" });
      }
      for (const p of scored) {
        if (tiers.length >= 3) break;
        if (tiers.every((t) => t.plan.items !== p.items)) tiers.push({ plan: p, label: "其他候选" });
      }
    }
    plans = tiers.slice(0, 3);
    if (state.planIndex >= plans.length) state.planIndex = 0;
  }

  /* ---------------- 渲染：Hero ---------------- */
  function renderHero() {
    $("#heroFetched").textContent = D.meta.fetchedAt;
    $("#heroStore").textContent = "华旭国际大厦餐厅";
    $("#footFetched").textContent = D.meta.fetchedAt;

    const cal = D.calendar["2026-10"];
    const grid = $("#heroCal");
    grid.innerHTML = "";
    const cells = cal.cells.slice().sort((a, b) => a.col - b.col || a.row - b.row);
    const colors = { 0: "#ebedf0", 1: "#9be9a8", 2: "#40c463", 3: "#ffc72c", 4: "#f78140", 5: "#d93a3a" };
    cells.forEach((c) => {
      const d = document.createElement("i");
      d.className = "mini-cell";
      d.style.background = colors[c.level] || colors[0];
      d.title = c.kcal ? c.day + " 日：" + c.kcal + " kcal" : c.day + " 日：无数据";
      grid.appendChild(d);
    });
    $("#heroStat1").textContent = D.report.totalOrders + " 单";
    $("#heroStat2").textContent = fmtInt(D.report.avgMealKcal) + " kcal";
    $("#heroStat3").textContent = money(D.report.totalSpendFen);
  }

  /* ---------------- 渲染：KPI ---------------- */
  const KPI_ICONS = ["🧾", "🍔", "💰", "📈"];
  function renderKpis() {
    const r = D.report;
    const items = [
      { k: "有效订单", v: r.totalOrders, unit: "单", n: "另有 " + r.refundedOrders + " 单已退款，已过滤", alert: false },
      { k: "平均每单", v: r.avgMealKcal, unit: "kcal", n: "本餐目标 " + fmtInt(target.meal) + " kcal", alert: r.avgMealKcal > target.meal },
      { k: "累计支出", v: (r.totalSpendFen / 100).toFixed(2), unit: "元", n: "近 5 周 · 到店 + 麦乐送", alert: false },
      { k: "最高单日", v: r.maxDay.kcal, unit: "kcal", n: r.maxDay.date.slice(5) + " · 超标天数 " + overDays() + "/" + r.daysWithData, alert: true },
    ];
    const box = $("#kpis");
    box.innerHTML = items
      .map(
        (it, i) => `
        <div class="kpi ${it.alert ? "alert" : ""}" style="animation-delay:${i * 70}ms">
          <div class="k">${KPI_ICONS[i]} ${it.k}</div>
          <div class="v" data-count="${it.v}">0<small>${it.unit}</small></div>
          <div class="n">${it.n}</div>
        </div>`
      )
      .join("");
    box.classList.add("in");
    $$(".kpi .v", box).forEach((el) => countUp(el, Number(el.dataset.count)));
  }

  function countUp(el, to) {
    const isFloat = String(to).includes(".");
    const unit = el.querySelector("small") ? el.querySelector("small").outerHTML : "";
    const start = performance.now();
    const dur = 760;
    const step = (now) => {
      const p = Math.min(1, (now - start) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      const v = to * eased;
      el.innerHTML = (isFloat ? v.toFixed(2) : fmtInt(v)) + unit;
      if (p < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  function overDays() {
    let over = 0;
    Object.keys(D.calendar).forEach((k) => {
      D.calendar[k].cells.forEach((c) => {
        if (c.kcal && c.kcal > target.daily) over++;
      });
    });
    return over;
  }

  /* ---------------- 渲染：习惯画像 ---------------- */
  const HABIT_ICONS = ["🏆", "📊", "🗓", "🌙", "🥤", "🎯", "❓"];
  function renderHabits() {
    const box = $("#habitList");
    const habits = D.report.habits.map((h, i) => {
      if (h.startsWith("有数据的")) {
        const days = D.report.daysWithData;
        const over = overDays();
        return "有数据的 " + days + " 天里，" + over + " 天超过每日目标 " + fmtInt(target.daily) + " kcal。";
      }
      return h;
    });
    box.innerHTML = habits
      .map(
        (h, i) => `
        <li class="habit">
          <span class="ico">${HABIT_ICONS[i % HABIT_ICONS.length]}</span>
          <span>${decorate(h)}</span>
        </li>`
      )
      .join("");
  }

  function decorate(text) {
    return text
      .replace(/「([^」]+)」/g, "「<b>$1</b>」")
      .replace(/(\d+(?:\.\d+)?\s*kcal)/g, "<em>$1</em>")
      .replace(/(\d+\s*份|\d+\s*单)/g, "<em>$1</em>");
  }

  /* ---------------- 渲染：日历 ---------------- */
  function renderCalendar() {
    const cal = D.calendar[state.month];
    const grid = $("#calGrid");
    const colors = { 0: "#f1f2f4", 1: "#9be9a8", 2: "#40c463", 3: "#ffc72c", 4: "#f78140", 5: "#d93a3a" };
    const cells = cal.cells.slice().sort((a, b) => a.col - b.col || a.row - b.row);
    grid.innerHTML = "";
    cells.forEach((c, i) => {
      const el = document.createElement("div");
      el.className = "cal-cell";
      let lv = c.level;
      if (c.kcal != null) {
        const ratio = c.kcal / target.daily;
        lv = ratio <= 0.5 ? 1 : ratio <= 1 ? 2 : ratio <= 1.2 ? 3 : ratio <= 1.5 ? 4 : 5;
      }
      el.dataset.lv = lv;
      el.dataset.day = c.day;
      el.dataset.kcal = c.kcal == null ? "" : c.kcal;
      if (c.kcal && c.kcal > target.daily) el.classList.add("over");
      el.style.animation = "rise .34s cubic-bezier(.22,1,.36,1) both";
      el.style.animationDelay = Math.min(i * 6, 260) + "ms";
      grid.appendChild(el);
    });
    const over = overDays();
    $("#calMeta").innerHTML =
      "有数据 <b>" + cal.stats.daysWithData + "</b> 天 · 本月超标 <b>" + cal.stats.overDays +
      "</b> 天 · 日均 <b>" + fmtInt(cal.stats.avgKcal) + "</b> kcal";
  }

  function bindCalendarTooltip() {
    const tip = $("#tooltip");
    document.addEventListener("mouseover", (e) => {
      const cell = e.target.closest(".cal-cell");
      if (!cell) return;
      const day = Number(cell.dataset.day);
      const kcal = cell.dataset.kcal;
      tip.innerHTML = state.month.slice(5) + " 月 " + day + " 日 · " +
        (kcal ? "<b>" + fmtInt(Number(kcal)) + " kcal</b>" : "无数据");
      tip.classList.add("on");
    });
    document.addEventListener("mousemove", (e) => {
      const cell = e.target.closest(".cal-cell");
      if (!cell) return;
      tip.style.left = e.clientX + "px";
      tip.style.top = e.clientY - 8 + "px";
    });
    document.addEventListener("mouseout", (e) => {
      if (e.target.closest(".cal-cell")) tip.classList.remove("on");
    });
  }

  /* ---------------- 渲染：订单 ---------------- */
  function renderOrders() {
    $("#orderList").innerHTML = D.recentOrders
      .map((o) => {
        const names = o.items.map((i) => i.name + (i.qty > 1 ? "×" + i.qty : "")).join(" + ");
        return `
        <div class="order-row">
          <span class="t">${o.time}</span>
          <span class="items" title="${names}">${names}</span>
          <span class="kcal ${o.kcal == null ? "unknown" : ""}">${
            o.kcal == null ? "热量未知 · " + o.unknown + " 项" : fmtInt(o.kcal) + " kcal"
          }</span>
          <span class="pay">${money(o.totalFen)}</span>
        </div>`;
      })
      .join("");
  }

  /* ---------------- 渲染：门店 ---------------- */
  function renderStores() {
    $("#storeRow").innerHTML = D.stores
      .slice(0, 3)
      .map(
        (s, i) => `
      <button class="store ${i === 0 ? "on" : ""}" data-code="${s.storeCode}">
        <span class="dist">${s.distance} m</span>
        <div class="name">${s.storeName.replace("麦当劳", "")}</div>
        <div class="addr">${s.address}</div>
        <div class="meta">
          <span class="open">● 营业中</span>
          <span>${s.businessStartTime}–${s.businessEndTime}</span>
          <span>${s.storeCode}</span>
        </div>
      </button>`
      )
      .join("");

    $$(".store").forEach((b) =>
      b.addEventListener("click", () => {
        $$(".store").forEach((x) => x.classList.remove("on"));
        b.classList.add("on");
        toast("已切换门店（菜单快照仍为华旭国际大厦餐厅）");
      })
    );
  }

  /* ---------------- 渲染：菜单 ---------------- */
  const CATS = ["全部", "主食", "小食", "饮料", "甜品"];
  function renderChips() {
    $("#menuChips").innerHTML = CATS.map(
      (c) => `<button class="chip ${c === state.filter ? "on" : ""}" data-cat="${c}">${c}</button>`
    ).join("");
    $$("#menuChips .chip").forEach((b) =>
      b.addEventListener("click", () => {
        state.filter = b.dataset.cat;
        renderChips();
        renderMenu();
      })
    );
  }

  function renderMenu() {
    const list = D.menu.filter((m) => state.filter === "全部" || m.category === state.filter);
    $("#menuGrid").innerHTML = list
      .map(
        (m) => `
      <div class="dish ${m.known ? "" : "unk"}" data-code="${m.code}">
        <div class="pic">
          <img src="${m.image}" alt="${m.name}" loading="lazy" referrerpolicy="no-referrer"
               onerror="this.style.display='none';this.nextElementSibling.style.display='grid'">
          <span class="fallback" style="display:none">🍔</span>
        </div>
        <div class="body">
          <div class="nm">${m.name}</div>
          <div class="row">
            <span class="price">${money(m.priceFen)}</span>
            ${
              m.known
                ? `<span class="badge kcal">${fmtInt(m.kcal)} kcal</span>`
                : `<span class="badge unknown">热量未知</span>`
            }
          </div>
          <div class="src">${
            m.known
              ? "蛋白质 " + m.protein + " g · 钠 " + m.sodium + " mg" + (m.sizeNote ? " · " + m.sizeNote : "")
              : "未收录 → 不估算、不参与推荐"
          }</div>
        </div>
      </div>`
      )
      .join("");

    $$("#menuGrid .dish").forEach((el) =>
      el.addEventListener("click", () => {
        const m = D.menu.find((x) => x.code === el.dataset.code);
        if (!m) return;
        if (!m.known) {
          toast("「" + m.name + "」本地营养库未收录 → 标记未知，绝不估算");
        } else {
          toast(m.name + "：" + m.kcal + " kcal · 蛋白质 " + m.protein + " g · 钠 " + m.sodium + " mg");
        }
      })
    );
  }

  function renderCoupons() {
    $("#couponList").innerHTML =
      D.coupons.real
        .map(
          (c) => `<div class="coupon-line">${c.title}<em>${c.productName} · ${c.valid}</em></div>`
        )
        .join("") +
      `<div class="coupon-line" style="color:#8a6d1f">演示券：满 35 减 6 / 鲜萃咖啡减 3 元<em>真实券不适用本单，仅用于演示比价逻辑</em></div>`;
  }

  /* ---------------- 渲染：方案 ---------------- */
  function renderPlans() {
    const box = $("#plans");
    $("#planSub").textContent =
      "目标 " + fmtInt(target.meal) + " kcal · 评分 = −|热量−目标|×0.6 + 蛋白质×2 − 超钠×0.05 − 超糖×1.5";

    // 三张卡共用同一刻度，避免「每张卡自己最大」造成误读
    const maxAbs = Math.max(
      60,
      ...plans.map((t) =>
        Math.max(
          Math.abs(t.plan.breakdown.proteinBonus),
          Math.abs(t.plan.breakdown.sodiumPenalty),
          Math.abs(t.plan.breakdown.kcalPenalty)
        )
      )
    );

    box.innerHTML = plans
      .map((t, idx) => {
        const p = t.plan;
        const b = p.breakdown;
        const w = (v) => Math.min(100, (Math.abs(v) / maxAbs) * 100);
        return `
        <article class="plan ${idx === state.planIndex ? "on" : ""}" data-idx="${idx}">
          <span class="tag">${t.label}</span>
          <h4>${p.kcal} kcal · ${money(p.totalFen)}</h4>
          <div class="scoreline">营养评分 <b>${p.score.toFixed(1)}</b> ／ 目标 ${fmtInt(target.meal)} kcal</div>

          <div class="dishlist">
            ${p.items
              .map(
                (i) => `<div class="dishline">
                  <img src="${imgByCode[i.code] || ""}" alt="" referrerpolicy="no-referrer"
                       onerror="this.style.visibility='hidden'">
                  <span class="nm">${i.name}</span>
                  <span class="kc">${i.kcal == null ? "未知" : fmtInt(i.kcal)}</span>
                </div>`
              )
              .join("")}
          </div>

          <div class="bars">
            <div class="bar-row"><span class="lb">热量贴近</span><span class="tr"><i style="width:${w(
              b.kcalPenalty
            )}%;background:#ffc72c"></i></span><span class="vl" style="color:#b8860b">${b.kcalPenalty}</span></div>
            <div class="bar-row"><span class="lb">蛋白质</span><span class="tr"><i style="width:${w(
              b.proteinBonus
            )}%;background:#1e7b34"></i></span><span class="vl" style="color:#1e7b34">+${b.proteinBonus}</span></div>
            <div class="bar-row"><span class="lb">钠</span><span class="tr"><i style="width:${w(
              b.sodiumPenalty
            )}%;background:#e8892b"></i></span><span class="vl" style="color:#c06a12">${b.sodiumPenalty}</span></div>
            <div class="bar-row"><span class="lb">糖</span><span class="tr"><i style="width:${w(
              b.sugarPenalty
            )}%;background:#da291c"></i></span><span class="vl" style="color:#da291c">${b.sugarPenalty}</span></div>
          </div>

          <div class="macro">
            <div><b>${fmtInt(p.protein)}</b><span>蛋白质 g</span></div>
            <div><b>${fmtInt(p.sodium)}</b><span>钠 mg</span></div>
            <div><b>${fmtInt(p.sugar)}</b><span>糖 g</span></div>
          </div>

          <ul class="reasons">${p.reasons.slice(0, 4).map((r) => `<li>${r}</li>`).join("")}</ul>

          <div class="price">
            <div>
              <b>${money(p.totalFen)}</b>
              ${p.discountFen > 0 ? `<s>${money(p.subtotalFen)}</s>` : ""}
            </div>
            ${p.discountFen > 0 ? `<span class="save">省 ${money(p.discountFen)}</span>` : ""}
          </div>
        </article>`;
      })
      .join("");

    $$("#plans .plan").forEach((el) =>
      el.addEventListener("click", () => {
        state.planIndex = Number(el.dataset.idx);
        renderPlans();
        renderTicket();
        renderPayRows();
      })
    );
  }

  function refreshPlans() {
    rebuildPlans();
    renderPlans();
    renderTicket();
    renderPayRows();
  }

  /* ---------------- 渲染：小票 / 结算 ---------------- */
  function selectedPlan() {
    return plans[state.planIndex] || plans[0];
  }

  function renderTicket() {
    const t = selectedPlan();
    if (!t) return;
    const p = t.plan;
    const store = D.stores[0];
    $("#ticketStore").textContent = store.storeName;
    $("#ticketAddr").textContent = store.address + " · 距你 " + store.distance + " m · " + D.meta.beTypeLabel;
    $("#ticketNo").textContent = "#MCD-20261021-0944";

    $("#ticketItems").innerHTML = p.items
      .map(
        (i) => `
      <div class="ticket-item">
        <img src="${imgByCode[i.code] || ""}" alt="" referrerpolicy="no-referrer"
             onerror="this.style.visibility='hidden'">
        <div>
          <div class="nm">${i.name}</div>
          <div class="su">${i.kcal == null ? "热量未知" : fmtInt(i.kcal) + " kcal"} · ×1</div>
        </div>
        <div class="pr">${money(i.priceFen)}</div>
      </div>`
      )
      .join("");

    const isTop = p.items.map((i) => i.code).sort().join(",") === PRICED_CODES.join(",");
    const pc = D.priceCheck;
    let rows = "";
    if (isTop) {
      rows += `<div class="price-row"><span>官方原价</span><b>${money(pc.originalPrice)}</b></div>`;
      rows += `<div class="price-row off"><span>官方促销（calculate-price）</span><b>−${money(
        pc.officialDiscount
      )}</b></div>`;
      rows += `<div class="price-row"><span>官方计价复核</span><b>${money(pc.price)}</b></div>`;
    } else {
      rows += `<div class="price-row"><span>商品小计</span><b>${money(p.subtotalFen)}</b></div>`;
    }
    if (p.discountFen > 0) {
      rows += `<div class="price-row off"><span>演示券「${p.coupons.join("、")}」</span><b>−${money(
        p.discountFen
      )}</b></div>`;
    }
    rows += `<div class="price-row total"><span>合计</span><b>${money(p.totalFen)}</b></div>`;
    $("#ticketTotals").innerHTML = rows;
  }

  function renderPayRows() {
    const t = selectedPlan();
    if (!t) return;
    const p = t.plan;
    $("#payRows").innerHTML = `
      <div class="price-row"><span>商品小计</span><b>${money(p.subtotalFen)}</b></div>
      <div class="price-row off"><span>优惠</span><b>−${money(p.discountFen)}</b></div>
      <div class="price-row"><span>${D.meta.beTypeLabel} · ${state.takeway === "eat-in" ? "堂食" : "外带"}</span><b>0.00</b></div>
      <div class="price-row total"><span>应付</span><b>${money(p.totalFen)}</b></div>`;
  }

  function renderTakeway() {
    const list = D.priceCheck.takeWayList;
    $("#takeway").innerHTML = list
      .map(
        (t) => `<button data-code="${t.code}" class="${t.code === state.takeway ? "on" : ""}">
          <b>${t.title}</b><span>${t.subtitle}</span>
        </button>`
      )
      .join("");
    $$("#takeway button").forEach((b) =>
      b.addEventListener("click", () => {
        state.takeway = b.dataset.code;
        renderTakeway();
        renderPayRows();
      })
    );
  }

  /* ---------------- MCP 调用链 ---------------- */
  function renderTrace() {
    const rows = [
      { tool: "now-time-info", res: "2026-10-21 09:44:10 · GMT+08:00", status: "200" },
      { tool: "query-nearby-stores", res: "上海 · 人民广场 → 5 家门店（最近 144 m）", status: "200" },
      { tool: "query-meals", res: "storeCode 1450713 → 12 类目 / 82 款餐品", status: "200" },
      { tool: "query-store-coupons", res: "可用券 2 张（新人专享 7 折）", status: "200" },
      { tool: "calculate-price", res: "4 件商品 → 原价 ¥58.50 / 实付 ¥51.40", status: "200" },
      { tool: "create-order", res: "演示模式：不调用，不产生真实订单", status: "skip" },
    ];
    $("#traceRows").innerHTML = rows
      .map(
        (r, i) => `
      <div class="trace-row">
        <span class="idx">${i + 1}</span>
        <span class="tool">${r.tool}</span>
        <span class="res">${r.res}</span>
        <span class="${r.status === "200" ? "ok" : "skip"}">${r.status === "200" ? "● 200 OK" : "◌ SKIPPED"}</span>
      </div>`
      )
      .join("");
    $("#traceTime").textContent = D.meta.fetchedAt;
  }

  /* ---------------- 扫描动画 ---------------- */
  function runScan() {
    if (state.scanned) return Promise.resolve();
    const total = D.report.totalOrders;
    const bar = $("#scanBar");
    const fill = $("#scanFill");
    const count = $("#scanCount");
    const text = $("#scanText");
    return new Promise((resolve) => {
      let i = 0;
      text.textContent = "order-list → 逐单匹配营养数据…";
      const timer = setInterval(() => {
        i += 1;
        const p = Math.min(1, i / total);
        fill.style.width = p * 100 + "%";
        count.textContent = i + " / " + total;
        if (i >= total) {
          clearInterval(timer);
          state.scanned = true;
          text.textContent = "过滤 1 单退款 · 2 单含未知热量（不计入）· 审计完成";
          bar.style.background = "#14301f";
          renderKpis();
          renderHabits();
          renderCalendar();
          setTimeout(resolve, 280);
        }
      }, 28);
    });
  }

  /* ---------------- 骨架（等待扫描） ---------------- */
  function renderSkeleton() {
    const items = [
      ["🧾 有效订单", "单"],
      ["🍔 平均每单", "kcal"],
      ["💰 累计支出", "元"],
      ["📈 最高单日", "kcal"],
    ];
    $("#kpis").innerHTML = items
      .map(
        ([k, u]) =>
          `<div class="kpi"><div class="k">${k}</div><div class="v">—<small>${u}</small></div><div class="n">等待审计…</div></div>`
      )
      .join("");
    $("#habitList").innerHTML = `<li class="habit"><span class="ico">⏳</span><span>正在拉取 order-list，逐单匹配营养数据…</span></li>`;
    $("#calMeta").innerHTML = "等待审计…";
    $("#calGrid").innerHTML = "";
  }

  /* ---------------- Toast ---------------- */
  let toastTimer = null;
  function toast(msg) {
    let el = $("#toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "toast";
      el.className = "toast";
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add("on");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("on"), 2600);
  }

  /* ---------------- 下单弹窗 ---------------- */
  function openModal() {
    const t = selectedPlan();
    if (!t) return;
    const p = t.plan;
    const store = D.stores[0];
    const takeway = D.priceCheck.takeWayList.find((x) => x.code === state.takeway);
    $("#receiptMini").innerHTML = `
      <div><span>门店</span><b>${store.storeName.replace("麦当劳", "")}</b></div>
      <div><span>取餐方式</span><b>${takeway ? takeway.title : "堂食"}</b></div>
      <div><span>餐品</span><b>${p.items.length} 件</b></div>
      <div><span>热量</span><b>${fmtInt(p.kcal)} kcal</b></div>
      <div><span>合计</span><b style="color:#da291c">${money(p.totalFen)}</b></div>`;
    $("#modal").classList.add("on");
  }

  function bindModal() {
    $$("[data-close]").forEach((el) =>
      el.addEventListener("click", () => $("#modal").classList.remove("on"))
    );
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") $("#modal").classList.remove("on");
    });
    $("#payBtn").addEventListener("click", openModal);
  }

  /* ---------------- 导航与滚动 ---------------- */
  function bindScroll() {
    const sections = ["s1", "s2", "s3", "s4"].map((id) => $("#" + id));
    const links = $$("#navSteps a");

    // 导航高亮：视口中线所在的小节
    const navIO = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (!en.isIntersecting) return;
          const idx = sections.indexOf(en.target);
          links.forEach((l, i) => l.classList.toggle("active", i === idx));
        });
      },
      { rootMargin: "-45% 0px -50% 0px" }
    );
    sections.forEach((s) => navIO.observe(s));

    // 审计触发：02 区块一旦可见就跑扫描（对任意视口高度都成立）
    const scanIO = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting) {
            runScan();
            scanIO.disconnect();
          }
        });
      },
      { threshold: 0.15 }
    );
    scanIO.observe($("#s2"));

    const revealIO = new IntersectionObserver(
      (entries) => {
        entries.forEach((en) => {
          if (en.isIntersecting) {
            en.target.classList.add("in");
            revealIO.unobserve(en.target);
          }
        });
      },
      { threshold: 0.08 }
    );
    $$(".reveal").forEach((el) => revealIO.observe(el));

    window.addEventListener(
      "scroll",
      () => {
        const h = document.documentElement.scrollHeight - window.innerHeight;
        $("#navProgress").style.width = (h > 0 ? (window.scrollY / h) * 100 : 0) + "%";
      },
      { passive: true }
    );
  }

  /* ---------------- 一键演示 ---------------- */
  let autoRun = false;
  async function autoDemo() {
    const btn = $("#autoBtn");
    if (autoRun) return;
    autoRun = true;
    btn.classList.add("running");
    btn.textContent = "演示进行中…";

    const goto = (id) =>
      new Promise((r) => {
        document.querySelector(id).scrollIntoView({ behavior: "smooth", block: "start" });
        setTimeout(r, 900);
      });

    try {
      await goto("#s1");
      await new Promise((r) => setTimeout(r, 700));
      await goto("#s2");
      await new Promise((r) => setTimeout(r, 300));
      await runScan();
      await new Promise((r) => setTimeout(r, 900));
      await goto("#s3");
      await new Promise((r) => setTimeout(r, 1100));
      await goto("#s4");
      await new Promise((r) => setTimeout(r, 700));
      openModal();
    } finally {
      autoRun = false;
      btn.classList.remove("running");
      btn.textContent = "▶ 一键演示";
    }
  }

  /* ---------------- 初始化 ---------------- */
  function init() {
    computeTarget();
    paintTarget();
    bindProfile();
    renderHero();
    renderOrders();
    renderStores();
    renderChips();
    renderMenu();
    renderCoupons();
    renderTrace();
    renderTakeway();
    bindCalendarTooltip();
    bindModal();
    bindScroll();

    rebuildPlans();
    renderPlans();
    renderTicket();
    renderPayRows();

    $("#calTabs").addEventListener("click", (e) => {
      const b = e.target.closest("button[data-m]");
      if (!b) return;
      state.month = b.dataset.m;
      $$("#calTabs button").forEach((x) => x.classList.toggle("on", x === b));
      renderCalendar();
    });

    $("#regenBtn").addEventListener("click", () => {
      refreshPlans();
      toast("已按当前目标 " + fmtInt(target.meal) + " kcal 重新评分排序");
    });

    $("#autoBtn").addEventListener("click", autoDemo);

    // 首屏：链路 B 先留白，等滚动到 02 再跑审计动画
    renderSkeleton();
    state.scanned = false;
    $("#scanFill").style.width = "0%";
    $("#scanCount").textContent = "0 / " + D.report.totalOrders;
    $("#scanText").textContent = "准备拉取 order-list…";
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  // 带锚点打开时立即定位（截图/分享场景），不受平滑滚动影响
  if (location.hash && location.hash.length > 1) {
    const el = document.querySelector(location.hash);
    if (el) {
      setTimeout(() => {
        const html = document.documentElement;
        const prev = html.style.scrollBehavior;
        html.style.scrollBehavior = "auto";
        el.scrollIntoView({ block: "start" });
        html.style.scrollBehavior = prev || "";
      }, 60);
    }
  }
})();
