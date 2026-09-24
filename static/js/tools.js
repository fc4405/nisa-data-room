/* NISAデータ室 シミュレーター。scripts/calc.py と同じ計算式。入力値は送信されません。 */
(function () {
  "use strict";
  var TAX = 0.20315, LIFETIME = 18000000, GROWTH_SUB = 12000000, TSUMI = 1200000, GROWTH = 2400000, TOTAL = TSUMI + GROWTH;

  function num(form, name, def) {
    var v = parseFloat(form.elements[name].value);
    return isFinite(v) ? v : def;
  }
  function yen(v) { return Math.round(v).toLocaleString("ja-JP") + "円"; }
  function man(v) { return Math.round(v / 10000).toLocaleString("ja-JP") + "万円"; }
  function fv(monthly, rate, years, initial) {
    var n = Math.round(years * 12), r = rate / 12;
    if (r === 0) return initial + monthly * n;
    var g = Math.pow(1 + r, n);
    return initial * g + monthly * ((g - 1) / r);
  }
  function fillPlan(yearly, done) {
    var y = Math.min(yearly, TOTAL), t = Math.min(y, TSUMI), g = Math.max(0, y - t);
    var remain = Math.max(0, LIFETIME - done), years;
    if (remain === 0) years = 0;
    else if (y <= 0) years = Infinity;
    else if (g === 0) years = remain / t;
    else {
      var yg = GROWTH_SUB / g;
      years = (yg * y >= remain) ? remain / y : yg + (remain - yg * y) / t;
    }
    return { annual: y, tsumitate: t, growth: g, years: years, capped: yearly > TOTAL };
  }
  function taxMerit(monthly, rate, years, initial, fee) {
    var val = fv(monthly, rate - fee, years, initial), prin = initial + monthly * Math.round(years * 12);
    var gain = val - prin, tax = Math.max(0, gain) * TAX;
    return { value: val, principal: prin, gain: gain, tax: tax, netTaxable: val - tax, netNisa: val, overCap: prin > LIFETIME };
  }
  function row(k, v, cls) { return '<div class="kv' + (cls ? " " + cls : "") + '"><dt>' + k + "</dt><dd>" + v + "</dd></div>"; }
  function warn(msg) { return '<p class="warn">' + msg + "</p>"; }
  function siteBase() { return (typeof window !== "undefined" && window.SITE_BASE) || ""; }
  function link(path) { return siteBase() + path; }
  function fmtMonth(ym) { var p = ym.split("-"); return p[0] + "年" + parseInt(p[1], 10) + "月"; }

  /* 過去の指数データで、毎月一定額を積み立てたら現在いくらになるかを疑似計算する（信託報酬・税金・為替・分配金は考慮しない単純な口数モデル）。
     rows: [[ "YYYY-MM", 価格 ], ...]（昇順）、startYm: 開始月、monthly: 毎月の積立額（円）。 */
  function backtestDCA(rows, startYm, monthly) {
    var startIdx = -1;
    for (var i = 0; i < rows.length; i++) { if (rows[i][0] === startYm) { startIdx = i; break; } }
    if (startIdx < 0) return null;
    var units = 0, cumPrincipal = 0, path = [], worst = 0, worstYm = null;
    for (var j = startIdx; j < rows.length; j++) {
      var price = rows[j][1];
      if (price > 0) { units += monthly / price; cumPrincipal += monthly; }
      var value = units * price;
      path.push([rows[j][0], value]);
      var ratio = cumPrincipal > 0 ? (value - cumPrincipal) / cumPrincipal : 0;
      if (ratio < worst) { worst = ratio; worstYm = rows[j][0]; }
    }
    var lastPrice = rows[rows.length - 1][1], value = units * lastPrice;
    var months = rows.length - startIdx, years = months / 12;
    var cagr = (cumPrincipal > 0 && years > 0 && value > 0) ? (Math.pow(value / cumPrincipal, 1 / years) - 1) : null;
    return { value: value, principal: cumPrincipal, gain: value - cumPrincipal, months: months, years: years,
             cagr: cagr, worst: worst, worstYm: worstYm, path: path };
  }

  var tools = {
    "nisa-simulator": function (f) {
      var m = Math.max(0, num(f, "monthly", 0)), ini = Math.max(0, num(f, "initial", 0));
      var rate = num(f, "rate", 0) / 100, years = Math.max(1, Math.min(60, num(f, "years", 1))), fee = num(f, "fee", 0) / 100;
      var net = rate - fee, val = fv(m, net, years, ini), prin = ini + m * Math.round(years * 12), gain = val - prin;
      var h = "<dl>" + row("将来の評価額（概算）", "<strong>" + man(val) + "</strong>", "big") +
        row("投資した元本の合計", man(prin)) + row("運用益（概算）", man(gain)) +
        row("実質の想定年利（年利−コスト）", (net * 100).toFixed(2) + "%") +
        row("年間の投資額", man(m * 12)) + "</dl>";
      if (m * 12 > TOTAL) h += warn("年間の投資額が新NISAの年間上限（360万円）を超えています。超えた分はNISA口座では買えません。");
      if (prin > LIFETIME) h += warn("元本の合計が生涯投資枠（1,800万円）を超えます。枠は購入時の取得価額（簿価）で管理され、超える分は課税口座での投資になります（売却による枠の再利用は考慮していません）。");
      var rows = "", step = years > 30 ? 5 : (years > 15 ? 2 : 1);
      for (var y = step; y <= years; y += step) {
        rows += "<tr><th scope='row'>" + y + "年後</th><td>" + man(ini + m * y * 12) + "</td><td>" + man(fv(m, net, y, ini)) + "</td></tr>";
      }
      h += '<div class="table-wrap"><table><caption>年ごとの推移（概算）</caption><thead><tr><th scope="col">経過</th><th scope="col">元本</th><th scope="col">評価額</th></tr></thead><tbody>' + rows + "</tbody></table></div>";
      return h;
    },
    "tax-merit": function (f) {
      var m = Math.max(0, num(f, "monthly", 0)), ini = Math.max(0, num(f, "initial", 0));
      var rate = num(f, "rate", 0) / 100, years = Math.max(1, Math.min(60, num(f, "years", 1))), fee = num(f, "fee", 0) / 100;
      var r = taxMerit(m, rate, years, ini, fee);
      var h = "<dl>" + row("売却時の評価額（概算）", man(r.value)) + row("投資した元本の合計", man(r.principal)) +
        row("運用益（概算）", man(r.gain)) +
        row("課税口座なら引かれる税金（20.315%）", man(r.tax)) +
        row("課税口座の手取り（概算）", man(r.netTaxable)) +
        row("NISA口座の手取り（概算）", man(r.netNisa)) +
        row("NISAで省ける税金（概算）", "<strong>" + man(r.tax) + "</strong>", "big") + "</dl>";
      if (r.gain <= 0) h += '<p class="hint">運用益が出ない前提のため、省ける税金は0円です。非課税のメリットは、利益が出たときにだけ発生します。</p>';
      if (r.overCap) h += warn("元本の合計が生涯投資枠（1,800万円）を超えます。枠を超える分は課税口座での投資になるため、実際に省ける税金はこの計算より小さくなります。");
      if (m * 12 > TOTAL) h += warn("年間の投資額が新NISAの年間上限（360万円）を超えています。超えた分はNISA口座では買えません。");
      h += '<p class="hint">期間の最後に全額を売却した場合の単純な計算です。途中の分配金への課税、売却の時期、税制改正は考慮していません。NISA口座で出た損失は、他の口座の利益と通算できません。</p>';
      return h;
    },
    "fee-impact": function (f) {
      var m = Math.max(0, num(f, "monthly", 0)), years = Math.max(1, Math.min(60, num(f, "years", 1)));
      var rate = num(f, "rate", 0) / 100, a = num(f, "feeA", 0) / 100, b = num(f, "feeB", 0) / 100;
      var va = fv(m, rate - a, years, 0), vb = fv(m, rate - b, years, 0), prin = m * Math.round(years * 12);
      var diff = va - vb, more = diff >= 0 ? "A" : "B";
      var h = "<dl>" + row("商品A（コスト " + (a * 100).toFixed(2) + "%）", man(va)) +
        row("商品B（コスト " + (b * 100).toFixed(2) + "%）", man(vb)) +
        row("差額（" + more + "の方が多い）", "<strong>" + man(Math.abs(diff)) + "</strong>", "big") +
        row("元本の合計（共通）", man(prin)) + "</dl>";
      h += '<p class="hint">コストの差は毎年の運用成果から差し引かれるため、期間が長いほど差が広がります。ただし、実際の運用成績は商品ごとに異なり、コストが低い方が常に有利とは限りません。</p>';
      return h;
    },
    "frame-planner": function (f) {
      var m = Math.max(0, num(f, "monthly", 0)), bonus = Math.max(0, num(f, "bonus", 0)), done = Math.max(0, num(f, "done", 0));
      var yearly = m * 12 + bonus * 2, p = fillPlan(yearly, done);
      var yrs = p.years === Infinity ? "―" : (p.years === 0 ? "枠は使い切り済み" : p.years.toFixed(1) + "年");
      var h = "<dl>" + row("年間の投資額（想定）", man(yearly)) +
        row("うち つみたて投資枠", man(p.tsumitate) + "（上限120万円）") +
        row("うち 成長投資枠", man(p.growth) + "（上限240万円）") +
        row("生涯投資枠1,800万円に届くまで", "<strong>" + yrs + "</strong>", "big") +
        row("残りの枠（簿価）", man(Math.max(0, LIFETIME - done))) + "</dl>";
      if (p.capped) h += warn("年間の投資額が上限（360万円）を超えています。計算は上限の360万円で行っています。");
      if (p.growth > 0 && GROWTH_SUB / p.growth * (p.tsumitate + p.growth) < LIFETIME - done)
        h += '<p class="hint">成長投資枠の生涯上限（1,200万円）に先に届くため、その後はつみたて投資枠（年120万円）のみで枠を埋めていく計算になっています。</p>';
      return h;
    },
    "start-diagnosis": function (f) {
      var exp = f.elements["experience"].value, budget = f.elements["budget"].value, goal = f.elements["goal"].value;
      var manMap = { "1": 10000, "3": 30000, "5": 50000 };
      var monthly = manMap[budget] || (exp === "none" ? 5000 : 10000);
      var lines = [];
      lines.push("まずの目安として、月" + man(monthly) + "から考えてみましょう。");
      if (exp === "none") {
        lines.push("初めての場合は、まずつみたて投資枠だけを使う始め方がシンプルです。");
      } else if (exp === "much" && budget === "5") {
        lines.push("投資経験があり、まとまった金額を回せる場合は、つみたて投資枠に加えて成長投資枠の活用も選択肢になります。");
      } else {
        lines.push("まずはつみたて投資枠を中心に考え、慣れてきたら成長投資枠の活用を検討する順序がおすすめです。");
      }
      if (goal === "retire") {
        lines.push("老後の資金づくりが目的の場合、非課税保有期間が無期限という新NISAの特徴が活きやすいテーマです。");
      } else if (goal === "big") {
        lines.push("使う時期がある程度決まっている資金は、その時期が近づいたら、値動きの大きい商品の割合を見直すことも考えておくと安心です。");
      }
      var steps = [
        ["制度の全体像をつかむ（学ぶ順番ガイド）", "/guide/"],
        ["月" + man(monthly) + "で積立額をシミュレーションする", "/tools/nisa-simulator/"],
        ["証券口座を選ぶ基準を確認する", "/articles/nisa-kouza-erabikata/"],
        ["口座を開いたあとにやることを確認する", "/articles/nisa-kouza-kaisetsu-go-checklist/"]
      ];
      var h = '<div class="kv big"><dt>まずの積立額の目安</dt><dd>月' + man(monthly) + 'から</dd></div>';
      h += '<p class="hint">' + lines.join(" ") + '</p>';
      h += '<h3>次に進む順番</h3><ol class="roadmap">';
      steps.forEach(function (s) { h += '<li><a href="' + link(s[1]) + '">' + s[0] + '</a></li>'; });
      h += '</ol>';
      h += '<p class="hint">これは一般的な考え方の整理であり、投資の助言ではありません。金額や配分は、ご自身の家計状況に合わせて調整してください。</p>';
      return h;
    },
    "market-experience": (function () {
      function populateStart(f) {
        var idx = f.elements["index"].value;
        var data = (window.MARKET_EXPERIENCE_DATA || {})[idx];
        var sel = f.elements["start"], prevVal = sel.value;
        sel.innerHTML = "";
        if (!data || !data.rows || data.rows.length < 13) return false;
        var rows = data.rows;
        for (var i = 0; i <= rows.length - 13; i++) {
          var opt = document.createElement("option");
          opt.value = rows[i][0];
          opt.textContent = fmtMonth(rows[i][0]) + "から";
          sel.appendChild(opt);
        }
        var hasPrev = Array.prototype.some.call(sel.options, function (o) { return o.value === prevVal; });
        var tenYearsBack = rows.length > 121 ? rows[rows.length - 121][0] : rows[0][0];
        sel.value = hasPrev ? prevVal : tenYearsBack;
        return true;
      }
      return function (f) {
        var idx = f.elements["index"].value;
        if (f.dataset.expIndex !== idx) { populateStart(f); f.dataset.expIndex = idx; }
        var data = (window.MARKET_EXPERIENCE_DATA || {})[idx];
        if (!data || !data.rows || data.rows.length < 13) {
          return '<p class="table-note">この指数の過去データを準備中です。しばらくしてから、もう一度お試しください。</p>';
        }
        var monthly = Math.max(1000, num(f, "monthly", 30000));
        var startYm = f.elements["start"].value;
        var r = backtestDCA(data.rows, startYm, monthly);
        if (!r) return '<p class="table-note">開始月を選び直してください。</p>';
        var h = "<dl>" + row("現在の評価額（概算）", "<strong>" + man(r.value) + "</strong>", "big") +
          row("積み立てた元本の合計", man(r.principal)) +
          row("運用益（概算）", man(r.gain)) +
          row("積立期間", r.years.toFixed(1) + "年");
        if (r.cagr !== null) h += row("年率換算のリターン（概算）", (r.cagr * 100).toFixed(1) + "%");
        h += "</dl>";
        if (r.worst < -0.01) {
          h += '<p class="hint">途中、' + fmtMonth(r.worstYm) + '頃には、それまでの元本よりも評価額が約' +
            Math.abs(Math.round(r.worst * 100)) + '%少ない場面もありました。積立の価値は、期間中ずっと右肩上がりだったわけではありません。</p>';
        }
        var yearRows = [], lastYear = null;
        for (var k = 0; k < r.path.length; k++) {
          var ym = r.path[k][0], y = ym.slice(0, 4);
          if (y !== lastYear || k === r.path.length - 1) { yearRows.push([y + "年", man(r.path[k][1])]); lastYear = y; }
        }
        if (yearRows.length > 12) {
          var step = Math.ceil(yearRows.length / 12), thinned = [];
          for (var t = 0; t < yearRows.length - 1; t += step) thinned.push(yearRows[t]);
          thinned.push(yearRows[yearRows.length - 1]);
          yearRows = thinned;
        }
        var trs = yearRows.map(function (rr) { return "<tr><th scope='row'>" + rr[0] + "</th><td>" + rr[1] + "</td></tr>"; }).join("");
        h += '<div class="table-wrap"><table><caption>年末時点の評価額の推移（概算）</caption>' +
          '<thead><tr><th scope="col">年</th><th scope="col">評価額</th></tr></thead><tbody>' + trs + "</tbody></table></div>";
        h += '<p class="hint">' + data.name + 'の実際の指数データにもとづく疑似体験です。信託報酬・税金・為替（円換算）・分配金・売買コストは考慮していません。将来の運用成果を予測・保証するものではなく、特定の商品を推奨するものでもありません。</p>';
        return h;
      };
    })()
  };

  if (typeof document !== "undefined") document.querySelectorAll("form.calc").forEach(function (form) {
    var key = form.getAttribute("data-tool"), out = document.querySelector('[data-result="' + key + '"]');
    function run() { out.innerHTML = tools[key](form); }
    form.addEventListener("input", run);
    form.addEventListener("submit", function (e) { e.preventDefault(); run(); });
    run();
  });
  if (typeof module !== "undefined") module.exports = { fv: fv, fillPlan: fillPlan, taxMerit: taxMerit, backtestDCA: backtestDCA };
})();
