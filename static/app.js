// ── InstaScope Frontend ─────────────────────────────────────────────────────

// ── Upgrade Popup ──────────────────────────────────────────────────────────

function showUpgradePopup(message) {
    // Remove existing popup if any
    const existing = document.getElementById('upgradeOverlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id = 'upgradeOverlay';
    overlay.className = 'fixed inset-0 bg-black/70 flex items-center justify-center z-[100]';
    overlay.onclick = (e) => { if (e.target === overlay) overlay.remove(); };
    overlay.innerHTML = `
        <div class="bg-dark-800 border border-accent-500/30 rounded-2xl p-8 max-w-md mx-4 text-center animate-[fadeUp_0.3s_ease-out]">
            <div class="text-5xl mb-4">&#128274;</div>
            <h2 class="text-xl font-bold text-white mb-2">Upgrade to Pro</h2>
            <p class="text-gray-400 mb-6">${message || 'This feature requires a Pro subscription.'}</p>
            <div class="bg-dark-900 rounded-xl p-4 mb-6">
                <div class="text-3xl font-bold text-white mb-1">$5.50<span class="text-lg text-gray-400 font-normal">/month</span></div>
                <ul class="text-sm text-gray-300 text-left space-y-2 mt-4">
                    <li class="flex gap-2"><span class="text-green-400">&#10003;</span> Unlimited scans & tracking</li>
                    <li class="flex gap-2"><span class="text-green-400">&#10003;</span> Gender & demographic analysis</li>
                    <li class="flex gap-2"><span class="text-green-400">&#10003;</span> Ghost followers & lurkers</li>
                    <li class="flex gap-2"><span class="text-green-400">&#10003;</span> Content advisor & recommendations</li>
                    <li class="flex gap-2"><span class="text-green-400">&#10003;</span> Automatic daily scans</li>
                </ul>
            </div>
            <div class="flex gap-3">
                <a href="/pricing" class="flex-1 py-3 bg-gradient-to-r from-accent-500 to-pink-500 hover:brightness-110 text-white font-semibold rounded-xl transition text-center">
                    View Plans
                </a>
                <button onclick="document.getElementById('upgradeOverlay').remove()"
                    class="px-6 py-3 bg-dark-900 text-gray-400 rounded-xl hover:text-white transition">
                    Later
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(overlay);
}

function handleApiResponse(data, btn, defaultBtnText) {
    if (data.upgrade) {
        showUpgradePopup(data.error);
        if (btn) { btn.disabled = false; btn.textContent = defaultBtnText; }
        return true;
    }
    if (data.error) {
        alert(data.error);
        if (btn) { btn.disabled = false; btn.textContent = defaultBtnText; }
        return true;
    }
    return false;
}

function addProLock(elementId, featureName) {
    const el = document.getElementById(elementId);
    if (!el) return;
    el.style.position = 'relative';
    el.style.overflow = 'hidden';
    // Blur the content
    const children = el.children;
    for (let i = 0; i < children.length; i++) {
        children[i].style.filter = 'blur(6px)';
        children[i].style.pointerEvents = 'none';
        children[i].style.userSelect = 'none';
    }
    // Add lock overlay
    const overlay = document.createElement('div');
    overlay.className = 'absolute inset-0 flex flex-col items-center justify-center z-10 cursor-pointer';
    overlay.onclick = () => showUpgradePopup(`Unlock ${featureName} with Pro subscription.`);
    overlay.innerHTML = `
        <div class="bg-dark-900/80 backdrop-blur-sm rounded-xl px-6 py-4 text-center border border-accent-500/30 shadow-lg">
            <div class="text-2xl mb-1">&#128274;</div>
            <div class="text-sm font-semibold text-accent-400">Pro Feature</div>
            <div class="text-xs text-gray-400 mt-1">Click to upgrade</div>
        </div>
    `;
    el.appendChild(overlay);
}

function addProBadge(elementId) {
    const el = document.getElementById(elementId);
    if (!el) return;
    const badge = document.createElement('span');
    badge.className = 'ml-2 px-2 py-0.5 bg-accent-500/20 text-accent-400 rounded-full text-xs font-bold cursor-pointer';
    badge.textContent = 'PRO';
    badge.onclick = () => showUpgradePopup();
    el.appendChild(badge);
}

const chartDefaults = {
    color: '#9ca3af',
    borderColor: 'transparent',
    font: { family: 'Inter' },
};
Chart.defaults.color = '#9ca3af';
Chart.defaults.font.family = 'Inter';

// ── Search & Navigation ─────────────────────────────────────────────────────

function handleSearch(e) {
    e.preventDefault();
    const username = document.getElementById('usernameInput').value.trim().replace(/^@/, '');
    if (!username) return false;

    const postLimit = parseInt(document.getElementById('postLimit').value);
    const deep = document.getElementById('deepToggle').checked;
    const btn = document.getElementById('analyzeBtn');
    btn.disabled = true;
    btn.textContent = 'Starting...';

    fetch('/api/analyze', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, post_limit: postLimit, deep }),
    })
        .then(r => r.json())
        .then(data => {
            if (data.error) {
                alert(data.error);
                btn.disabled = false;
                btn.textContent = 'Analyze';
                return;
            }
            window.location.href = `/dashboard/${data.username}?task=${data.task_id}`;
        })
        .catch(err => {
            alert('Error: ' + err.message);
            btn.disabled = false;
            btn.textContent = 'Analyze';
        });

    return false;
}

// ── History ─────────────────────────────────────────────────────────────────

function loadHistory() {
    fetch('/api/history')
        .then(r => r.json())
        .then(items => {
            if (!items.length) return;
            document.getElementById('historySection').classList.remove('hidden');
            const grid = document.getElementById('historyGrid');
            grid.innerHTML = items.map(h => `
                <a href="/dashboard/${h.username}" class="bg-dark-800 border border-gray-800 rounded-xl p-4 hover:border-accent-500 transition group block">
                    <div class="flex items-center gap-3 mb-3">
                        <img src="${h.profile_pic_url || ''}" alt="" class="w-12 h-12 rounded-full bg-gray-700 object-cover"
                             onerror="this.src='data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect fill=%22%23374151%22 width=%22100%22 height=%22100%22/><text x=%2250%22 y=%2255%22 text-anchor=%22middle%22 fill=%22%239ca3af%22 font-size=%2240%22>?</text></svg>'">
                        <div class="flex-1 min-w-0">
                            <div class="font-semibold truncate group-hover:text-accent-400 transition">
                                @${h.username} ${h.is_verified ? '<span class="text-blue-400">✓</span>' : ''}
                            </div>
                            <div class="text-xs text-gray-500 truncate">${h.full_name}</div>
                        </div>
                    </div>
                    <div class="flex items-center justify-between text-sm">
                        <span class="text-gray-400">${formatNumber(h.followers)} followers</span>
                        <span class="px-2 py-0.5 rounded-full text-xs font-semibold ${scoreColor(h.authenticity_score)}">
                            ${h.authenticity_score}/100
                        </span>
                    </div>
                    <div class="text-xs text-gray-600 mt-2">${timeAgo(h.analyzed_at)}</div>
                </a>
            `).join('');
        });
}

// ── Polling ─────────────────────────────────────────────────────────────────

function pollStatus(taskId) {
    fetch(`/api/status/${taskId}`)
        .then(r => r.json())
        .then(data => {
            if (data.lost) { loadReport(USERNAME); return; }
            if (data.error && !data.status) { showError(data.error); return; }
            document.getElementById('progressText').textContent = data.progress || 'Working...';
            if (data.status === 'done') renderDashboard(data.result);
            else if (data.status === 'error') showError(data.error);
            else setTimeout(() => pollStatus(taskId), 1500);
        })
        .catch(() => setTimeout(() => pollStatus(taskId), 3000));
}

function loadReport(username) {
    fetch(`/api/report/${username}`)
        .then(r => {
            if (!r.ok) throw new Error('No report found — start a new analysis from the home page');
            return r.json();
        })
        .then(data => renderDashboard(data))
        .catch(err => showError(err.message));
}

function showError(msg) {
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('errorState').classList.remove('hidden');
    document.getElementById('errorText').textContent = msg;
}

// ── Dashboard Renderer ──────────────────────────────────────────────────────

function renderDashboard(report) {
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('dashboard').classList.remove('hidden');

    renderProfileHeader(report.profile);
    renderAuthenticity(report.authenticity);
    renderAge(report.audience_age);
    renderDemographics(report.demographics);
    renderBusiness(report.business_insights);
    renderCampaigns(report.campaigns);
}

// ── Profile Header ──────────────────────────────────────────────────────────

function renderProfileHeader(p) {
    const pic = document.getElementById('profilePic');
    pic.src = p.profile_pic_url || '';
    pic.onerror = () => pic.src = 'data:image/svg+xml,<svg xmlns=%22http://www.w3.org/2000/svg%22 viewBox=%220 0 100 100%22><rect fill=%22%23374151%22 width=%22100%22 height=%22100%22/><text x=%2250%22 y=%2255%22 text-anchor=%22middle%22 fill=%22%239ca3af%22 font-size=%2240%22>?</text></svg>';

    document.getElementById('profileUsername').textContent = '@' + p.username;
    document.getElementById('profileName').textContent = p.full_name || '';
    document.getElementById('profileBio').textContent = p.biography || '';

    if (p.is_verified) document.getElementById('verifiedBadge').classList.remove('hidden');

    if (p.external_url) {
        const link = document.getElementById('profileUrl');
        link.href = p.external_url;
        link.textContent = p.external_url.replace(/^https?:\/\//, '');
        link.classList.remove('hidden');
    }

    document.getElementById('statPosts').textContent = formatNumber(p.posts_count);
    document.getElementById('statFollowers').textContent = formatNumber(p.followers);
    document.getElementById('statFollowing').textContent = formatNumber(p.following);
}

// ── Authenticity Gauge ──────────────────────────────────────────────────────

function renderAuthenticity(auth) {
    const score = auth.authenticity_score;
    const color = score >= 80 ? '#22c55e' : score >= 60 ? '#eab308' : score >= 40 ? '#f97316' : '#ef4444';
    const bgColor = '#1f2937';

    document.getElementById('authScore').textContent = score;
    document.getElementById('authScore').style.color = color;

    const verdictEl = document.getElementById('authVerdict');
    verdictEl.textContent = auth.verdict;
    verdictEl.style.color = color;

    new Chart(document.getElementById('authGauge'), {
        type: 'doughnut',
        data: {
            datasets: [{
                data: [score, 100 - score],
                backgroundColor: [color, bgColor],
                borderWidth: 0,
            }]
        },
        options: {
            cutout: '78%',
            responsive: true,
            maintainAspectRatio: true,
            plugins: { legend: { display: false }, tooltip: { enabled: false } },
            animation: { animateRotate: true, duration: 1200 },
        }
    });

    const positives = document.getElementById('authPositives');
    positives.innerHTML = (auth.positive_signals || []).map(s =>
        `<li class="flex gap-2"><span class="text-green-400 flex-shrink-0">✓</span> ${s}</li>`
    ).join('');

    const flags = document.getElementById('authFlags');
    const flagItems = auth.red_flags || [];
    flags.innerHTML = flagItems.length
        ? flagItems.map(s => `<li class="flex gap-2"><span class="text-red-400 flex-shrink-0">⚠</span> ${s}</li>`).join('')
        : '<li class="text-gray-600">No red flags detected</li>';
}

// ── Age Chart ───────────────────────────────────────────────────────────────

function renderAge(age) {
    document.getElementById('ageMethod').textContent = age.method || '';
    document.getElementById('primaryAge').textContent = age.primary_age_group || '';

    const dist = age.estimated_age_distribution || {};
    const labels = Object.keys(dist);
    const values = Object.values(dist).map(v => parseFloat(String(v).replace('%', '')) || 0);

    new Chart(document.getElementById('ageChart'), {
        type: 'bar',
        data: {
            labels,
            datasets: [{
                data: values,
                backgroundColor: labels.map((l, i) =>
                    l === age.primary_age_group
                        ? '#8b5cf6'
                        : `rgba(139, 92, 246, ${0.2 + i * 0.12})`
                ),
                borderRadius: 6,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: {
                    beginAtZero: true,
                    ticks: { callback: v => v + '%' },
                    grid: { color: '#1f2937' },
                },
                x: { grid: { display: false } },
            },
        }
    });
}

// ── Demographics ────────────────────────────────────────────────────────────

function renderDemographics(demo) {
    if (!demo) return;

    document.getElementById('demoPlaceholder').classList.add('hidden');
    document.getElementById('demoCharts').classList.remove('hidden');

    const gd = demo.gender_distribution || {};
    new Chart(document.getElementById('genderChart'), {
        type: 'bar',
        data: {
            labels: ['Female', 'Male', 'Unknown'],
            datasets: [{
                data: [
                    gd.female?.percentage || 0,
                    gd.male?.percentage || 0,
                    gd.unknown?.percentage || 0,
                ],
                backgroundColor: ['#ec4899', '#3b82f6', '#6b7280'],
                borderRadius: 6,
            }]
        },
        options: {
            indexAxis: 'y',
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                x: { ticks: { callback: v => v + '%' }, grid: { color: '#1f2937' } },
                y: { grid: { display: false } },
            },
        }
    });

    const countries = demo.detected_countries || {};
    if (Object.keys(countries).length) {
        document.getElementById('countriesList').innerHTML = `
            <h3 class="text-sm font-semibold text-gray-400 mb-2">Detected Countries</h3>
            <div class="flex flex-wrap gap-2">
                ${Object.entries(countries).map(([c, n]) =>
                    `<span class="px-2 py-1 bg-dark-900 rounded-lg text-xs">${c} <span class="text-accent-400">${n}</span></span>`
                ).join('')}
            </div>`;
    }
}

// ── Business Insights ───────────────────────────────────────────────────────

function renderBusiness(biz) {
    const metrics = [
        { label: 'Account Tier', value: biz.account_tier, color: 'text-accent-400' },
        { label: 'Engagement Rate', value: biz.avg_engagement_rate, color: 'text-green-400' },
        { label: 'Est. Post Value', value: biz.estimated_post_value, color: 'text-yellow-400' },
        { label: 'Posts / Week', value: biz.posts_per_week, color: 'text-blue-400' },
    ];

    document.getElementById('bizMetrics').innerHTML = metrics.map(m => `
        <div class="bg-dark-900 rounded-xl p-4 text-center">
            <div class="text-xs text-gray-500 uppercase mb-1">${m.label}</div>
            <div class="${m.color} font-bold text-lg">${m.value}</div>
        </div>
    `).join('');

    // Content mix donut
    const mix = biz.content_mix || {};
    const typeLabels = { GraphImage: 'Images', GraphVideo: 'Videos', GraphSidecar: 'Carousels' };
    new Chart(document.getElementById('contentMixChart'), {
        type: 'doughnut',
        data: {
            labels: Object.keys(mix).map(k => typeLabels[k] || k),
            datasets: [{
                data: Object.values(mix),
                backgroundColor: ['#3b82f6', '#8b5cf6', '#ec4899'],
                borderWidth: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            plugins: {
                legend: { position: 'bottom', labels: { padding: 16, usePointStyle: true } },
            },
        }
    });

    // Top posts
    const topPosts = document.getElementById('topPosts');
    const byLikes = biz.top_posts_by_likes || [];
    const byComments = biz.top_posts_by_comments || [];

    let html = '';
    if (byLikes.length) {
        html += `<div>
            <h3 class="text-sm font-semibold text-gray-400 mb-2">Most Liked</h3>
            ${byLikes.map(p => `
                <a href="https://www.instagram.com/p/${p.shortcode}/" target="_blank"
                   class="block bg-dark-900 rounded-lg p-3 mb-2 hover:bg-gray-800 transition">
                    <span class="text-accent-400 font-mono text-sm">${p.shortcode}</span>
                    <span class="text-gray-400 ml-2">${p.likes > 0 ? formatNumber(p.likes) + ' likes' : 'likes hidden'}</span>
                </a>
            `).join('')}
        </div>`;
    }
    if (byComments.length) {
        html += `<div>
            <h3 class="text-sm font-semibold text-gray-400 mb-2">Most Commented</h3>
            ${byComments.map(p => `
                <a href="https://www.instagram.com/p/${p.shortcode}/" target="_blank"
                   class="block bg-dark-900 rounded-lg p-3 mb-2 hover:bg-gray-800 transition">
                    <span class="text-accent-400 font-mono text-sm">${p.shortcode}</span>
                    <span class="text-gray-400 ml-2">${formatNumber(p.comments)} comments</span>
                </a>
            `).join('')}
        </div>`;
    }
    topPosts.innerHTML = html;

    // Posting best times
    const bestDay = biz.best_posting_day || 'N/A';
    const bestHours = (biz.best_posting_hours_utc || []).join(', ') || 'N/A';

    // Add extra metric cards for timing
    document.getElementById('bizMetrics').innerHTML += `
        <div class="bg-dark-900 rounded-xl p-4 text-center">
            <div class="text-xs text-gray-500 uppercase mb-1">Best Day</div>
            <div class="text-pink-400 font-bold text-lg">${bestDay}</div>
        </div>
        <div class="bg-dark-900 rounded-xl p-4 text-center">
            <div class="text-xs text-gray-500 uppercase mb-1">Best Hours (UTC)</div>
            <div class="text-orange-400 font-bold text-sm">${bestHours}</div>
        </div>
        <div class="bg-dark-900 rounded-xl p-4 text-center">
            <div class="text-xs text-gray-500 uppercase mb-1">Avg Likes</div>
            <div class="text-blue-400 font-bold text-lg">${formatNumber(biz.avg_likes)}</div>
        </div>
        <div class="bg-dark-900 rounded-xl p-4 text-center">
            <div class="text-xs text-gray-500 uppercase mb-1">Avg Video Views</div>
            <div class="text-purple-400 font-bold text-lg">${formatNumber(biz.avg_video_views)}</div>
        </div>
    `;
}

// ── Campaigns ───────────────────────────────────────────────────────────────

function renderCampaigns(camp) {
    // Metrics
    document.getElementById('campMetrics').innerHTML = [
        { label: 'Sponsored Posts', value: camp.sponsored_posts_detected, color: 'text-yellow-400' },
        { label: 'Posts Analyzed', value: camp.total_posts_analyzed, color: 'text-gray-300' },
        { label: 'Sponsorship Rate', value: camp.sponsorship_rate, color: 'text-orange-400' },
    ].map(m => `
        <div class="bg-dark-900 rounded-xl p-4 text-center">
            <div class="text-xs text-gray-500 uppercase mb-1">${m.label}</div>
            <div class="${m.color} font-bold text-xl">${m.value}</div>
        </div>
    `).join('');

    // Brand partners
    const partners = camp.recurring_brand_partners || {};
    const bp = document.getElementById('brandPartners');
    if (Object.keys(partners).length) {
        bp.innerHTML = Object.entries(partners).map(([brand, count]) => `
            <div class="flex items-center gap-3">
                <div class="flex-1 bg-dark-900 rounded-lg overflow-hidden h-6">
                    <div class="h-full bg-accent-600/40 rounded-lg" style="width: ${Math.min(100, count * 20)}%"></div>
                </div>
                <span class="text-sm min-w-0">
                    <span class="text-accent-400">@${brand}</span>
                    <span class="text-gray-500 ml-1">${count}x</span>
                </span>
            </div>
        `).join('');
    } else {
        bp.innerHTML = '<p class="text-gray-600 text-sm">No recurring brand partners detected</p>';
    }

    // Top hashtags
    const hashtags = camp.top_hashtags || {};
    document.getElementById('topHashtags').innerHTML = Object.entries(hashtags).slice(0, 15).map(([tag, count]) => `
        <span class="px-3 py-1.5 bg-dark-900 rounded-full text-sm hover:bg-accent-600/20 transition cursor-default">
            #${tag} <span class="text-gray-500 ml-1">${count}</span>
        </span>
    `).join('');

    // Posting calendar
    const calendar = camp.posting_calendar || {};
    if (Object.keys(calendar).length > 1) {
        new Chart(document.getElementById('calendarChart'), {
            type: 'bar',
            data: {
                labels: Object.keys(calendar).map(m => m.slice(2)), // "2025-03" -> "25-03"
                datasets: [{
                    data: Object.values(calendar),
                    backgroundColor: '#8b5cf6',
                    borderRadius: 4,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    y: { beginAtZero: true, ticks: { stepSize: 1 }, grid: { color: '#1f2937' } },
                    x: { grid: { display: false } },
                },
            }
        });
    }

    // Sponsored posts table
    const sposts = camp.sponsored_posts || [];
    if (sposts.length) {
        document.getElementById('sponsoredTable').classList.remove('hidden');
        document.getElementById('sponsoredBody').innerHTML = sposts.map(sp => `
            <tr class="border-b border-gray-800">
                <td class="py-2 px-3 text-gray-400">${sp.date?.slice(0, 10) || ''}</td>
                <td class="py-2 px-3">
                    <a href="https://www.instagram.com/p/${sp.post}/" target="_blank" class="text-accent-400 hover:underline font-mono">${sp.post}</a>
                </td>
                <td class="py-2 px-3">
                    ${(sp.signals || []).map(s => `<span class="inline-block px-2 py-0.5 bg-yellow-500/10 text-yellow-400 rounded text-xs mr-1">${s}</span>`).join('')}
                </td>
                <td class="py-2 px-3 text-gray-400">${(sp.mentions || []).map(m => '@' + m).join(', ')}</td>
            </tr>
        `).join('');
    }
}

// ── Utilities ───────────────────────────────────────────────────────────────

function formatNumber(n) {
    if (n == null || n === 'N/A') return '—';
    n = Number(n);
    if (n >= 1000000) return (n / 1000000).toFixed(1) + 'M';
    if (n >= 1000) return (n / 1000).toFixed(1) + 'K';
    return String(n);
}

function scoreColor(score) {
    if (score >= 80) return 'bg-green-500/20 text-green-400';
    if (score >= 60) return 'bg-yellow-500/20 text-yellow-400';
    if (score >= 40) return 'bg-orange-500/20 text-orange-400';
    return 'bg-red-500/20 text-red-400';
}

function timeAgo(iso) {
    if (!iso) return '';
    const diff = Date.now() - new Date(iso).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return mins + 'm ago';
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return hrs + 'h ago';
    const days = Math.floor(hrs / 24);
    return days + 'd ago';
}

// ── Unfollower Tracker ─────────────────────────────────────────────────────

let allUnfollowerProfiles = [];

function startScan() {
    const username = typeof USERNAME !== 'undefined' ? USERNAME : '';
    if (!username) return;

    const btn = document.getElementById('scanBtn');
    btn.disabled = true;
    btn.textContent = 'Starting scan...';

    fetch('/api/unfollowers/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username }),
    })
        .then(r => r.json())
        .then(data => {
            if (handleApiResponse(data, btn, 'Scan Followers Now')) return;
            // Show loading and start polling
            document.getElementById('loadingOverlay').classList.remove('hidden');
            document.getElementById('firstTimeMsg').classList.add('hidden');
            document.getElementById('oneSnapshotMsg').classList.add('hidden');
            document.getElementById('resultsSection').classList.add('hidden');
            pollUnfollowerStatus(data.task_id);
        })
        .catch(err => {
            alert('Error: ' + err.message);
            btn.disabled = false;
            btn.textContent = 'Scan Followers Now';
        });
}

function pollUnfollowerStatus(taskId) {
    fetch(`/api/status/${taskId}`)
        .then(r => r.json())
        .then(data => {
            if (data.lost) { loadUnfollowerReport(USERNAME); return; }
            if (data.error && !data.status) { showUnfollowerError(data.error); return; }
            const progress = document.getElementById('progressText');
            if (progress) progress.textContent = data.progress || 'Working...';
            if (data.status === 'done') renderUnfollowerDashboard(data.result);
            else if (data.status === 'error') showUnfollowerError(data.error);
            else setTimeout(() => pollUnfollowerStatus(taskId), 2000);
        })
        .catch(() => setTimeout(() => pollUnfollowerStatus(taskId), 3000));
}

function loadUnfollowerReport(username) {
    fetch(`/api/unfollowers/${username}`)
        .then(r => {
            if (!r.ok) {
                // No report yet — show first-time message
                document.getElementById('firstTimeMsg').classList.remove('hidden');
                throw null;
            }
            return r.json();
        })
        .then(data => {
            if (data) renderUnfollowerDashboard(data);
        })
        .catch(err => {
            if (err !== null) showUnfollowerError(err.message || 'Failed to load report');
        });
}

function showUnfollowerError(msg) {
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('errorState').classList.remove('hidden');
    document.getElementById('errorText').textContent = msg;
    const btn = document.getElementById('scanBtn');
    if (btn) { btn.disabled = false; btn.textContent = 'Scan Followers Now'; }
}

function renderUnfollowerDashboard(report) {
    document.getElementById('loadingOverlay').classList.add('hidden');
    const btn = document.getElementById('scanBtn');
    if (btn) { btn.disabled = false; btn.textContent = 'Scan Followers Now'; }

    // No comparison yet (first snapshot)
    if (!report.comparison) {
        document.getElementById('oneSnapshotMsg').classList.remove('hidden');
        const snapCount = report.latest_snapshot?.count || report.profile_follower_count || 0;
        document.getElementById('snapshotCount').textContent = formatNumber(snapCount);
        if (report.latest_snapshot?.timestamp) {
            document.getElementById('snapshotTime').textContent = 'Taken: ' + new Date(report.latest_snapshot.timestamp).toLocaleString();
        }
        return;
    }

    document.getElementById('firstTimeMsg').classList.add('hidden');
    document.getElementById('oneSnapshotMsg').classList.add('hidden');
    document.getElementById('resultsSection').classList.remove('hidden');

    const comp = report.comparison;
    const analysis = report.unfollower_analysis || {};
    const newAnalysis = report.new_follower_analysis || {};

    // Use profile count as fallback when follower list couldn't be scraped
    const followerCount = comp.new_count || report.profile_follower_count || 0;

    // Show login warning if needed
    if (report.login_required) {
        const warn = document.createElement('div');
        warn.className = 'bg-yellow-500/10 border border-yellow-500/30 rounded-xl p-4 mb-4 text-sm text-yellow-400';
        warn.innerHTML = 'This report was generated without login — follower list is empty. Connect your Instagram session (top banner) and <strong>scan again</strong> to get full results.';
        document.getElementById('summaryCards').parentNode.insertBefore(warn, document.getElementById('summaryCards'));
    }

    // Summary cards
    document.getElementById('summaryCards').innerHTML = [
        { label: 'Current Followers', value: formatNumber(followerCount), color: 'text-blue-400' },
        { label: 'Unfollowed', value: comp.unfollower_count, color: 'text-red-400' },
        { label: 'New Followers', value: comp.new_follower_count, color: 'text-green-400' },
        { label: 'Net Change', value: (comp.net_change >= 0 ? '+' : '') + comp.net_change, color: comp.net_change >= 0 ? 'text-green-400' : 'text-red-400' },
        { label: 'Snapshots', value: report.snapshot_count, color: 'text-accent-400' },
    ].map(m => `
        <div class="bg-dark-800 rounded-xl p-4 text-center border border-gray-800">
            <div class="text-xs text-gray-500 uppercase mb-1">${m.label}</div>
            <div class="${m.color} font-bold text-2xl">${m.value}</div>
        </div>
    `).join('');

    // Gender chart
    renderUnfollowerGenderChart(analysis.gender_breakdown || {});

    // Account type chart
    renderAccountTypeChart(analysis);

    // Insights
    renderInsights(analysis.insights || [], comp);

    // History timeline
    if (report.history && report.history.length > 0) {
        renderHistoryChart(report.history);
    }

    // Unfollower list
    allUnfollowerProfiles = analysis.profiles || [];
    renderUnfollowerList(allUnfollowerProfiles);
    document.getElementById('unfollowerBadge').textContent = comp.unfollower_count;

    // New followers list
    const newProfiles = newAnalysis.profiles || [];
    renderNewFollowerList(newProfiles);
    document.getElementById('newFollowerBadge').textContent = comp.new_follower_count;
}

function renderUnfollowerGenderChart(genderBreakdown) {
    const canvas = document.getElementById('unfollowerGenderChart');
    if (!canvas) return;

    new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: ['Female', 'Male', 'Unknown'],
            datasets: [{
                data: [
                    genderBreakdown.female?.percentage || 0,
                    genderBreakdown.male?.percentage || 0,
                    genderBreakdown.unknown?.percentage || 0,
                ],
                backgroundColor: ['#ec4899', '#3b82f6', '#6b7280'],
                borderWidth: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            plugins: {
                legend: { position: 'bottom', labels: { padding: 12, usePointStyle: true, color: '#9ca3af' } },
                tooltip: {
                    callbacks: { label: ctx => ctx.label + ': ' + ctx.parsed.toFixed(1) + '%' }
                },
            },
        }
    });
}

function renderAccountTypeChart(analysis) {
    const canvas = document.getElementById('accountTypeChart');
    if (!canvas) return;

    const total = analysis.total || 1;
    const privateCount = analysis.private_accounts || 0;
    const publicCount = total - privateCount;
    const noNameCount = analysis.no_name_accounts || 0;
    const namedCount = total - noNameCount;

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: ['Private', 'Public', 'No Name', 'Has Name'],
            datasets: [{
                data: [privateCount, publicCount, noNameCount, namedCount],
                backgroundColor: ['#f97316', '#22c55e', '#ef4444', '#3b82f6'],
                borderRadius: 6,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: true, ticks: { stepSize: 1 }, grid: { color: '#1f2937' } },
                x: { grid: { display: false } },
            },
        }
    });
}

function renderInsights(insights, comp) {
    const list = document.getElementById('insightsList');
    if (!list) return;

    const items = [...insights];

    // Add time context
    if (comp.old_timestamp && comp.new_timestamp) {
        const from = new Date(comp.old_timestamp).toLocaleDateString();
        const to = new Date(comp.new_timestamp).toLocaleDateString();
        items.unshift(`Comparing snapshots from ${from} to ${to}`);
    }

    if (comp.net_change > 0) {
        items.push(`Net gain of ${comp.net_change} followers since last scan`);
    } else if (comp.net_change < 0) {
        items.push(`Net loss of ${Math.abs(comp.net_change)} followers since last scan`);
    }

    if (items.length === 0) {
        items.push('No notable patterns detected in unfollowers');
    }

    list.innerHTML = items.map(s =>
        `<li class="flex gap-2 items-start"><span class="text-accent-400 flex-shrink-0 mt-0.5">&#8226;</span> ${s}</li>`
    ).join('');
}

function renderHistoryChart(history) {
    const section = document.getElementById('historySection');
    if (!section) return;
    section.classList.remove('hidden');

    const labels = history.map(h => {
        const d = new Date(h.to);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    });

    new Chart(document.getElementById('historyChart'), {
        type: 'line',
        data: {
            labels,
            datasets: [
                {
                    label: 'Total Followers',
                    data: history.map(h => h.new_count),
                    borderColor: '#8b5cf6',
                    backgroundColor: 'rgba(139, 92, 246, 0.1)',
                    fill: true,
                    tension: 0.3,
                    yAxisID: 'y',
                },
                {
                    label: 'Unfollowed',
                    data: history.map(h => h.unfollower_count),
                    borderColor: '#ef4444',
                    backgroundColor: 'rgba(239, 68, 68, 0.1)',
                    fill: true,
                    tension: 0.3,
                    yAxisID: 'y1',
                },
                {
                    label: 'New Followers',
                    data: history.map(h => h.new_follower_count),
                    borderColor: '#22c55e',
                    backgroundColor: 'rgba(34, 197, 94, 0.1)',
                    fill: true,
                    tension: 0.3,
                    yAxisID: 'y1',
                },
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'index', intersect: false },
            plugins: {
                legend: { position: 'bottom', labels: { padding: 16, usePointStyle: true } },
            },
            scales: {
                y: {
                    position: 'left',
                    grid: { color: '#1f2937' },
                    title: { display: true, text: 'Total Followers', color: '#9ca3af' },
                },
                y1: {
                    position: 'right',
                    grid: { display: false },
                    title: { display: true, text: 'Changes', color: '#9ca3af' },
                    beginAtZero: true,
                },
                x: { grid: { display: false } },
            },
        }
    });
}

function renderUnfollowerList(profiles) {
    const list = document.getElementById('unfollowerList');
    const noMsg = document.getElementById('noUnfollowers');

    if (!profiles || profiles.length === 0) {
        list.classList.add('hidden');
        noMsg.classList.remove('hidden');
        return;
    }

    list.classList.remove('hidden');
    noMsg.classList.add('hidden');

    list.innerHTML = profiles.map(p => {
        const genderIcon = p.gender === 'female' ? '<span class="text-pink-400">F</span>'
            : p.gender === 'male' ? '<span class="text-blue-400">M</span>'
            : '<span class="text-gray-500">?</span>';
        const privateBadge = p.is_private ? '<span class="px-1.5 py-0.5 bg-orange-500/10 text-orange-400 rounded text-xs">Private</span>' : '';
        const verifiedBadge = p.is_verified ? '<span class="text-blue-400 ml-1">&#10003;</span>' : '';

        return `
            <div class="unfollower-item flex items-center gap-3 bg-dark-900 rounded-xl p-3 hover:bg-gray-800/50 transition"
                 data-gender="${p.gender}">
                <div class="w-10 h-10 rounded-full bg-gray-700 flex items-center justify-center text-lg font-bold flex-shrink-0">
                    ${genderIcon}
                </div>
                <div class="flex-1 min-w-0">
                    <div class="flex items-center gap-1">
                        <a href="https://www.instagram.com/${p.username}/" target="_blank"
                           class="text-accent-400 hover:underline font-semibold truncate">@${p.username}</a>
                        ${verifiedBadge}
                    </div>
                    <div class="text-xs text-gray-500 truncate">${p.full_name || 'No name'}</div>
                </div>
                <div class="flex gap-2 items-center flex-shrink-0">
                    ${privateBadge}
                </div>
            </div>
        `;
    }).join('');
}

function renderNewFollowerList(profiles) {
    const list = document.getElementById('newFollowerList');
    const noMsg = document.getElementById('noNewFollowers');

    if (!profiles || profiles.length === 0) {
        list.classList.add('hidden');
        noMsg.classList.remove('hidden');
        return;
    }

    list.classList.remove('hidden');
    noMsg.classList.add('hidden');

    list.innerHTML = profiles.map(p => `
        <div class="flex items-center gap-3 bg-dark-900 rounded-xl p-3">
            <div class="w-8 h-8 rounded-full bg-green-900/30 flex items-center justify-center text-green-400 text-sm flex-shrink-0">+</div>
            <div class="flex-1 min-w-0">
                <a href="https://www.instagram.com/${p.username}/" target="_blank"
                   class="text-green-400 hover:underline font-semibold text-sm truncate">@${p.username}</a>
                <span class="text-xs text-gray-500 ml-2">${p.full_name || ''}</span>
            </div>
        </div>
    `).join('');
}

function filterList(gender) {
    // Update active button
    document.querySelectorAll('.filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === gender);
        btn.classList.toggle('bg-accent-600', btn.dataset.filter === gender);
        btn.classList.toggle('text-white', btn.dataset.filter === gender);
    });

    if (gender === 'all') {
        renderUnfollowerList(allUnfollowerProfiles);
    } else {
        renderUnfollowerList(allUnfollowerProfiles.filter(p => p.gender === gender));
    }
}

// ── Ghost Followers & Lurkers ──────────────────────────────────────────────

let allGhostProfiles = [];

function startLurkerScan() {
    const username = typeof USERNAME !== 'undefined' ? USERNAME : '';
    if (!username) return;

    const btn = document.getElementById('scanBtn');
    btn.disabled = true;
    btn.textContent = 'Starting scan...';

    const postLimit = parseInt(document.getElementById('postLimitSelect')?.value || 20);

    fetch('/api/lurkers/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, post_limit: postLimit }),
    })
        .then(r => r.json())
        .then(data => {
            if (handleApiResponse(data, btn, 'Scan Now')) return;
            document.getElementById('loadingOverlay').classList.remove('hidden');
            document.getElementById('firstTimeMsg').classList.add('hidden');
            document.getElementById('resultsSection').classList.add('hidden');
            pollLurkerStatus(data.task_id);
        })
        .catch(err => {
            alert('Error: ' + err.message);
            btn.disabled = false;
            btn.textContent = 'Scan Now';
        });
}

function pollLurkerStatus(taskId) {
    fetch(`/api/status/${taskId}`)
        .then(r => r.json())
        .then(data => {
            if (data.lost) { loadLurkerReport(USERNAME); return; }
            if (data.error && !data.status) { showLurkerError(data.error); return; }
            const progress = document.getElementById('progressText');
            if (progress) progress.textContent = data.progress || 'Working...';
            if (data.status === 'done') renderLurkerDashboard(data.result);
            else if (data.status === 'error') showLurkerError(data.error);
            else setTimeout(() => pollLurkerStatus(taskId), 2000);
        })
        .catch(() => setTimeout(() => pollLurkerStatus(taskId), 3000));
}

function loadLurkerReport(username) {
    fetch(`/api/lurkers/${username}`)
        .then(r => {
            if (!r.ok) {
                document.getElementById('firstTimeMsg').classList.remove('hidden');
                throw null;
            }
            return r.json();
        })
        .then(data => {
            if (data) renderLurkerDashboard(data);
        })
        .catch(err => {
            if (err !== null) showLurkerError(err.message || 'Failed to load report');
        });
}

function showLurkerError(msg) {
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('errorState').classList.remove('hidden');
    document.getElementById('errorText').textContent = msg;
    const btn = document.getElementById('scanBtn');
    if (btn) { btn.disabled = false; btn.textContent = 'Scan Now'; }
}

function renderLurkerDashboard(report) {
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('firstTimeMsg').classList.add('hidden');
    document.getElementById('resultsSection').classList.remove('hidden');
    const btn = document.getElementById('scanBtn');
    if (btn) { btn.disabled = false; btn.textContent = 'Scan Now'; }

    const s = report.summary || {};

    // Summary cards
    document.getElementById('summaryCards').innerHTML = [
        { label: 'Followers', value: formatNumber(s.total_followers), color: 'text-blue-400' },
        { label: 'Ghost Followers', value: formatNumber(s.ghost_followers_count), color: 'text-gray-400' },
        { label: 'Secret Fans', value: s.secret_fans_count, color: 'text-pink-400' },
        { label: 'Story Stalkers', value: s.story_stalkers_count, color: 'text-cyan-400' },
        { label: 'Ghost %', value: s.ghost_followers_percentage + '%', color: s.ghost_followers_percentage > 50 ? 'text-red-400' : 'text-green-400' },
    ].map(m => `
        <div class="bg-dark-800 rounded-xl p-4 text-center border border-gray-800">
            <div class="text-xs text-gray-500 uppercase mb-1">${m.label}</div>
            <div class="${m.color} font-bold text-2xl">${m.value}</div>
        </div>
    `).join('');

    // Insights
    const insightsList = document.getElementById('insightsList');
    const insights = report.insights || [];
    if (insights.length) {
        insightsList.innerHTML = insights.map(s =>
            `<li class="flex gap-2 items-start"><span class="text-cyan-400 flex-shrink-0 mt-0.5">&#8226;</span> ${s}</li>`
        ).join('');
    } else {
        document.getElementById('insightsBar').classList.add('hidden');
    }

    // Gender charts
    renderGenderDoughnut('ghostGenderChart', report.ghost_gender);
    renderGenderDoughnut('fanGenderChart', report.secret_fans_gender);

    if (s.story_stalkers_count > 0) {
        renderGenderDoughnut('stalkerGenderChart', report.story_stalkers_gender);
    } else {
        document.getElementById('stalkerChartContainer').classList.add('hidden');
        document.getElementById('noStoryData').classList.remove('hidden');
    }

    // Top engagers
    renderTopEngagers(report.top_engagers || []);

    // Secret fans
    renderSecretFans(report.secret_fans || []);
    const fanBadge = document.getElementById('secretFanBadge');
    if (fanBadge) fanBadge.textContent = s.secret_fans_count || 0;

    // Story stalkers
    renderStoryStalkers(report.story_stalkers || []);
    const stalkerBadge = document.getElementById('stalkerBadge');
    if (stalkerBadge) stalkerBadge.textContent = s.story_stalkers_count || 0;

    // Ghost followers
    allGhostProfiles = report.ghost_followers || [];
    renderGhostList(allGhostProfiles);
    const ghostBadge = document.getElementById('ghostBadge');
    if (ghostBadge) ghostBadge.textContent = formatNumber(s.ghost_followers_count);
}

function renderGenderDoughnut(canvasId, genderData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !genderData || !Object.keys(genderData).length) return;

    new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: ['Female', 'Male', 'Unknown'],
            datasets: [{
                data: [
                    genderData.female?.percentage || 0,
                    genderData.male?.percentage || 0,
                    genderData.unknown?.percentage || 0,
                ],
                backgroundColor: ['#ec4899', '#3b82f6', '#6b7280'],
                borderWidth: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '60%',
            plugins: {
                legend: { position: 'bottom', labels: { padding: 10, usePointStyle: true, color: '#9ca3af', font: { size: 11 } } },
                tooltip: { callbacks: { label: ctx => ctx.label + ': ' + ctx.parsed.toFixed(1) + '%' } },
            },
        }
    });
}

function renderTopEngagers(engagers) {
    const container = document.getElementById('topEngagersList');
    if (!container) return;

    const top = engagers.slice(0, 12);
    container.innerHTML = top.map((e, i) => {
        const medal = i === 0 ? '&#129351;' : i === 1 ? '&#129352;' : i === 2 ? '&#129353;' : '';
        const genderColor = e.gender === 'female' ? 'text-pink-400' : e.gender === 'male' ? 'text-blue-400' : 'text-gray-500';

        return `
            <div class="bg-dark-900 rounded-xl p-3 flex items-center gap-3">
                <div class="w-8 h-8 rounded-full bg-accent-600/20 flex items-center justify-center text-sm font-bold flex-shrink-0 ${genderColor}">
                    ${medal || (i + 1)}
                </div>
                <div class="flex-1 min-w-0">
                    <a href="https://www.instagram.com/${e.username}/" target="_blank"
                       class="text-accent-400 hover:underline font-semibold text-sm truncate block">@${e.username}</a>
                    <div class="text-xs text-gray-500">${e.full_name || ''}</div>
                </div>
                <div class="text-right flex-shrink-0">
                    <div class="text-xs text-gray-400">${e.likes} likes, ${e.comments} comments</div>
                    <div class="text-xs text-accent-400">${e.engagement_rate}% of posts</div>
                </div>
            </div>
        `;
    }).join('');
}

function renderSecretFans(fans) {
    const list = document.getElementById('secretFansList');
    const noMsg = document.getElementById('noSecretFans');
    if (!list) return;

    if (!fans.length) {
        list.classList.add('hidden');
        noMsg.classList.remove('hidden');
        return;
    }

    list.classList.remove('hidden');
    noMsg.classList.add('hidden');

    list.innerHTML = fans.map(f => {
        const genderIcon = f.gender === 'female' ? '<span class="text-pink-400">F</span>'
            : f.gender === 'male' ? '<span class="text-blue-400">M</span>'
            : '<span class="text-gray-500">?</span>';

        return `
            <div class="flex items-center gap-3 bg-dark-900 rounded-xl p-3 hover:bg-gray-800/50 transition">
                <div class="w-10 h-10 rounded-full bg-pink-900/20 flex items-center justify-center text-lg font-bold flex-shrink-0">
                    ${genderIcon}
                </div>
                <div class="flex-1 min-w-0">
                    <a href="https://www.instagram.com/${f.username}/" target="_blank"
                       class="text-pink-400 hover:underline font-semibold truncate block">@${f.username}</a>
                    <div class="text-xs text-gray-500 truncate">${f.full_name || 'No name'}</div>
                </div>
                <div class="text-right flex-shrink-0">
                    <div class="text-sm text-pink-400 font-semibold">${f.total_interactions} interactions</div>
                    <div class="text-xs text-gray-500">${f.likes} likes, ${f.comments} comments on ${f.posts_engaged} posts</div>
                </div>
            </div>
        `;
    }).join('');
}

function renderStoryStalkers(stalkers) {
    const list = document.getElementById('stalkerList');
    const noMsg = document.getElementById('noStalkers');
    if (!list) return;

    if (!stalkers.length) {
        list.classList.add('hidden');
        noMsg.classList.remove('hidden');
        return;
    }

    list.classList.remove('hidden');
    noMsg.classList.add('hidden');

    list.innerHTML = stalkers.map(s => {
        const genderIcon = s.gender === 'female' ? '<span class="text-pink-400">F</span>'
            : s.gender === 'male' ? '<span class="text-blue-400">M</span>'
            : '<span class="text-gray-500">?</span>';
        const engageBadge = s.also_engages
            ? '<span class="px-1.5 py-0.5 bg-pink-500/10 text-pink-400 rounded text-xs">Also engages</span>'
            : '';

        return `
            <div class="flex items-center gap-3 bg-dark-900 rounded-xl p-3 hover:bg-gray-800/50 transition">
                <div class="w-10 h-10 rounded-full bg-cyan-900/20 flex items-center justify-center text-lg font-bold flex-shrink-0">
                    ${genderIcon}
                </div>
                <div class="flex-1 min-w-0">
                    <a href="https://www.instagram.com/${s.username}/" target="_blank"
                       class="text-cyan-400 hover:underline font-semibold truncate block">@${s.username}</a>
                    <div class="text-xs text-gray-500 truncate">${s.full_name || 'No name'}</div>
                </div>
                <div class="flex items-center gap-2 flex-shrink-0">
                    ${engageBadge}
                    <div class="text-sm text-cyan-400 font-semibold">${s.stories_viewed} stories</div>
                </div>
            </div>
        `;
    }).join('');
}

function renderGhostList(profiles) {
    const list = document.getElementById('ghostList');
    if (!list) return;

    if (!profiles.length) {
        list.innerHTML = '<div class="text-center py-8 text-gray-500">No ghost followers — everyone is engaging!</div>';
        return;
    }

    list.innerHTML = profiles.map(p => {
        const genderIcon = p.gender === 'female' ? '<span class="text-pink-400">F</span>'
            : p.gender === 'male' ? '<span class="text-blue-400">M</span>'
            : '<span class="text-gray-500">?</span>';
        const privateBadge = p.is_private ? '<span class="px-1.5 py-0.5 bg-orange-500/10 text-orange-400 rounded text-xs">Private</span>' : '';

        return `
            <div class="ghost-item flex items-center gap-3 bg-dark-900 rounded-xl p-3 hover:bg-gray-800/50 transition"
                 data-gender="${p.gender}">
                <div class="w-10 h-10 rounded-full bg-gray-700/50 flex items-center justify-center text-lg font-bold flex-shrink-0">
                    ${genderIcon}
                </div>
                <div class="flex-1 min-w-0">
                    <a href="https://www.instagram.com/${p.username}/" target="_blank"
                       class="text-gray-300 hover:underline font-semibold truncate block">@${p.username}</a>
                    <div class="text-xs text-gray-600 truncate">${p.full_name || 'No name'}</div>
                </div>
                <div class="flex gap-2 items-center flex-shrink-0">
                    ${privateBadge}
                    <span class="px-1.5 py-0.5 bg-gray-700/50 text-gray-500 rounded text-xs">Ghost</span>
                </div>
            </div>
        `;
    }).join('');
}

function filterGhosts(gender) {
    document.querySelectorAll('.ghost-filter-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === gender);
        btn.classList.toggle('bg-accent-600', btn.dataset.filter === gender);
        btn.classList.toggle('text-white', btn.dataset.filter === gender);
    });

    if (gender === 'all') {
        renderGhostList(allGhostProfiles);
    } else {
        renderGhostList(allGhostProfiles.filter(p => p.gender === gender));
    }
}

// ── Follow Relationships ───────────────────────────────────────────────────

let allNfbProfiles = [];
let allFansProfiles = [];

function startRelScan() {
    const username = typeof USERNAME !== 'undefined' ? USERNAME : '';
    if (!username) return;

    const btn = document.getElementById('scanBtn');
    btn.disabled = true;
    btn.textContent = 'Scanning...';

    fetch('/api/relationships/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username }),
    })
        .then(r => r.json())
        .then(data => {
            if (handleApiResponse(data, btn, 'Scan Now')) return;
            document.getElementById('loadingOverlay').classList.remove('hidden');
            document.getElementById('firstTimeMsg').classList.add('hidden');
            document.getElementById('resultsSection').classList.add('hidden');
            pollRelStatus(data.task_id);
        })
        .catch(err => { alert('Error: ' + err.message); btn.disabled = false; btn.textContent = 'Scan Now'; });
}

function pollRelStatus(taskId) {
    fetch(`/api/status/${taskId}`)
        .then(r => r.json())
        .then(data => {
            if (data.lost) { loadRelReport(USERNAME); return; }
            if (data.error && !data.status) { showRelError(data.error); return; }
            const p = document.getElementById('progressText');
            if (p) p.textContent = data.progress || 'Working...';
            if (data.status === 'done') renderRelDashboard(data.result);
            else if (data.status === 'error') showRelError(data.error);
            else setTimeout(() => pollRelStatus(taskId), 1500);
        })
        .catch(() => setTimeout(() => pollRelStatus(taskId), 3000));
}

function loadRelReport(username) {
    fetch(`/api/relationships/${username}`)
        .then(r => { if (!r.ok) { document.getElementById('firstTimeMsg').classList.remove('hidden'); throw null; } return r.json(); })
        .then(data => { if (data) renderRelDashboard(data); })
        .catch(err => { if (err !== null) showRelError(err.message || 'Failed to load'); });
}

function showRelError(msg) {
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('errorState').classList.remove('hidden');
    document.getElementById('errorText').textContent = msg;
    const btn = document.getElementById('scanBtn');
    if (btn) { btn.disabled = false; btn.textContent = 'Scan Now'; }
}

function renderRelDashboard(report) {
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('firstTimeMsg').classList.add('hidden');
    document.getElementById('resultsSection').classList.remove('hidden');
    const btn = document.getElementById('scanBtn');
    if (btn) { btn.disabled = false; btn.textContent = 'Scan Now'; }

    const isFree = report.is_free;

    // Summary cards
    document.getElementById('summaryCards').innerHTML = [
        { label: 'Followers', value: report.followers_count, color: 'text-blue-400' },
        { label: 'Following', value: report.following_count, color: 'text-purple-400' },
        { label: 'Mutual', value: report.mutual_count, color: 'text-accent-400' },
        { label: "Don't Follow Back", value: report.not_following_back_count, color: 'text-red-400' },
        { label: 'Your Fans', value: report.fans_count, color: 'text-green-400' },
    ].map(m => `
        <div class="bg-dark-800 rounded-xl p-4 text-center border border-gray-800">
            <div class="text-xs text-gray-500 uppercase mb-1">${m.label}</div>
            <div class="${m.color} font-bold text-2xl">${m.value}</div>
        </div>
    `).join('');

    // Gender charts — show fake data for free users (blurred)
    if (isFree) {
        // Render fake gender data so it looks enticing behind the blur
        renderRelGenderChart('nfbGenderChart', {female: {percentage: 45}, male: {percentage: 38}, unknown: {percentage: 17}});
        renderRelGenderChart('fansGenderChart', {female: {percentage: 52}, male: {percentage: 31}, unknown: {percentage: 17}});
        // Add pro lock overlays
        setTimeout(() => {
            addProLock('nfbGenderSection', 'Gender Analysis');
            addProLock('fansGenderSection', 'Gender Analysis');
            addProLock('nfbFilterSection', 'Gender Filter');
            addProLock('fansFilterSection', 'Gender Filter');
        }, 100);
    } else {
        renderRelGenderChart('nfbGenderChart', report.not_following_back_gender);
        renderRelGenderChart('fansGenderChart', report.fans_gender);
    }

    // Lists
    allNfbProfiles = report.not_following_back || [];
    allFansProfiles = report.fans || [];

    document.getElementById('nfbBadge').textContent = allNfbProfiles.length;
    document.getElementById('fansBadge').textContent = allFansProfiles.length;

    // Show upgrade teaser for free users
    if (isFree) {
        const teaser = document.getElementById('upgradeTeaser');
        if (teaser) teaser.classList.remove('hidden');
    }
    document.getElementById('mutualBadge').textContent = report.mutual_count;

    renderProfileList('nfbList', allNfbProfiles, 'text-red-400');
    renderProfileList('fansList', allFansProfiles, 'text-green-400');
    renderProfileList('mutualList', report.mutual || [], 'text-accent-400');
}

function renderRelGenderChart(canvasId, genderData) {
    const canvas = document.getElementById(canvasId);
    if (!canvas || !genderData || !Object.keys(genderData).length) return;

    new Chart(canvas, {
        type: 'doughnut',
        data: {
            labels: ['Female', 'Male', 'Unknown'],
            datasets: [{
                data: [
                    genderData.female?.percentage || 0,
                    genderData.male?.percentage || 0,
                    genderData.unknown?.percentage || 0,
                ],
                backgroundColor: ['#ec4899', '#3b82f6', '#6b7280'],
                borderWidth: 0,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            cutout: '55%',
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => ctx.label + ': ' + ctx.parsed.toFixed(1) + '%' } },
            },
        }
    });
}

function renderProfileList(containerId, profiles, linkColor) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!profiles.length) {
        el.innerHTML = '<div class="text-center py-4 text-gray-600 text-sm">None</div>';
        return;
    }
    el.innerHTML = profiles.map(p => {
        const genderIcon = p.gender === 'female' ? '<span class="text-pink-400">F</span>'
            : p.gender === 'male' ? '<span class="text-blue-400">M</span>'
            : '<span class="text-gray-500">?</span>';
        const verifiedBadge = p.is_verified ? ' <span class="text-blue-400">&#10003;</span>' : '';
        const privateBadge = p.is_private ? '<span class="px-1.5 py-0.5 bg-orange-500/10 text-orange-400 rounded text-xs">Private</span>' : '';

        return `
            <div class="rel-item flex items-center gap-3 bg-dark-900 rounded-xl p-2.5 hover:bg-gray-800/50 transition" data-gender="${p.gender}">
                <div class="w-8 h-8 rounded-full bg-gray-700/50 flex items-center justify-center text-sm font-bold flex-shrink-0">
                    ${genderIcon}
                </div>
                <div class="flex-1 min-w-0">
                    <a href="https://www.instagram.com/${p.username}/" target="_blank"
                       class="${linkColor} hover:underline font-semibold text-sm truncate block">@${p.username}${verifiedBadge}</a>
                    <div class="text-xs text-gray-600 truncate">${p.full_name || ''}</div>
                </div>
                ${privateBadge}
            </div>
        `;
    }).join('');
}

function filterNfb(gender) {
    document.querySelectorAll('.nfb-filter').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === gender);
        btn.classList.toggle('bg-accent-600', btn.dataset.filter === gender);
        btn.classList.toggle('text-white', btn.dataset.filter === gender);
    });
    const filtered = gender === 'all' ? allNfbProfiles : allNfbProfiles.filter(p => p.gender === gender);
    renderProfileList('nfbList', filtered, 'text-red-400');
}

function filterFans(gender) {
    document.querySelectorAll('.fans-filter').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.filter === gender);
        btn.classList.toggle('bg-accent-600', btn.dataset.filter === gender);
        btn.classList.toggle('text-white', btn.dataset.filter === gender);
    });
    const filtered = gender === 'all' ? allFansProfiles : allFansProfiles.filter(p => p.gender === gender);
    renderProfileList('fansList', filtered, 'text-green-400');
}

// ── Content Advisor ────────────────────────────────────────────────────────

function startAdvisorScan() {
    const username = typeof USERNAME !== 'undefined' ? USERNAME : '';
    if (!username) return;
    const btn = document.getElementById('scanBtn');
    btn.disabled = true; btn.textContent = 'Analyzing...';
    const postLimit = parseInt(document.getElementById('postLimitSelect')?.value || 50);

    fetch('/api/advisor/scan', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, post_limit: postLimit }),
    })
        .then(r => r.json())
        .then(data => {
            if (handleApiResponse(data, btn, 'Analyze Content')) return;
            document.getElementById('loadingOverlay').classList.remove('hidden');
            document.getElementById('firstTimeMsg').classList.add('hidden');
            document.getElementById('resultsSection').classList.add('hidden');
            pollAdvisorStatus(data.task_id);
        })
        .catch(err => { alert('Error: ' + err.message); btn.disabled = false; btn.textContent = 'Analyze Content'; });
}

function pollAdvisorStatus(taskId) {
    fetch(`/api/status/${taskId}`)
        .then(r => r.json())
        .then(data => {
            if (data.lost) { loadAdvisorReport(USERNAME); return; }
            if (data.error && !data.status) { showAdvisorError(data.error); return; }
            const p = document.getElementById('progressText');
            if (p) p.textContent = data.progress || 'Working...';
            if (data.status === 'done') renderAdvisorDashboard(data.result);
            else if (data.status === 'error') showAdvisorError(data.error);
            else setTimeout(() => pollAdvisorStatus(taskId), 1500);
        })
        .catch(() => setTimeout(() => pollAdvisorStatus(taskId), 3000));
}

function loadAdvisorReport(username) {
    fetch(`/api/advisor/${username}`)
        .then(r => { if (!r.ok) { document.getElementById('firstTimeMsg').classList.remove('hidden'); throw null; } return r.json(); })
        .then(data => { if (data) renderAdvisorDashboard(data); })
        .catch(err => { if (err !== null) showAdvisorError(err.message || 'Failed to load'); });
}

function showAdvisorError(msg) {
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('errorState').classList.remove('hidden');
    document.getElementById('errorText').textContent = msg;
    const btn = document.getElementById('scanBtn');
    if (btn) { btn.disabled = false; btn.textContent = 'Analyze Content'; }
}

function renderAdvisorDashboard(report) {
    document.getElementById('loadingOverlay').classList.add('hidden');
    document.getElementById('firstTimeMsg').classList.add('hidden');
    document.getElementById('resultsSection').classList.remove('hidden');
    const btn = document.getElementById('scanBtn');
    if (btn) { btn.disabled = false; btn.textContent = 'Analyze Content'; }

    // Recommendations
    const recsList = document.getElementById('recsList');
    const recs = report.recommendations || [];
    recsList.innerHTML = recs.map(r =>
        `<li class="flex gap-3 items-start">
            <span class="text-yellow-400 text-lg flex-shrink-0">&#9733;</span>
            <span class="text-gray-200">${r}</span>
        </li>`
    ).join('') || '<li class="text-gray-500">Not enough data for recommendations</li>';

    // Summary cards
    const bestDay = report.best_day ? report.best_day.day : 'N/A';
    const bestHour = report.best_hours?.length ? report.best_hours[0].hour + ':00 UTC' : 'N/A';
    document.getElementById('summaryCards').innerHTML = [
        { label: 'Posts Analyzed', value: report.posts_analyzed || 0, color: 'text-blue-400' },
        { label: 'Best Day', value: bestDay, color: 'text-yellow-400' },
        { label: 'Best Hour', value: bestHour, color: 'text-amber-400' },
        { label: 'Followers', value: formatNumber(report.followers || 0), color: 'text-accent-400' },
    ].map(m => `
        <div class="bg-dark-800 rounded-xl p-4 text-center border border-gray-800">
            <div class="text-xs text-gray-500 uppercase mb-1">${m.label}</div>
            <div class="${m.color} font-bold text-xl">${m.value}</div>
        </div>
    `).join('');

    // Hours chart
    renderHoursChart(report.best_hours || []);

    // Engagement trend
    renderTrendChart(report.engagement_trend || []);

    // Content type chart
    renderTypeChart(report.content_type_performance || {});

    // Caption length chart
    renderCaptionChart(report.caption_length_performance || {});

    // Hashtags
    renderHashtagPerformance(report.hashtag_performance || {});

    // Follower correlation
    renderCorrelation(report.follower_correlation);
}

function renderHoursChart(bestHours) {
    const canvas = document.getElementById('hoursChart');
    if (!canvas) return;

    // Fill all 24 hours, highlight best ones
    const bestHourSet = new Set(bestHours.map(h => h.hour));
    const allHours = Array.from({length: 24}, (_, i) => i);
    const bestMap = {};
    bestHours.forEach(h => bestMap[h.hour] = h.avg_engagement);

    // We only have data for best hours, show them as bars
    const data = allHours.map(h => bestMap[h] || 0);
    const colors = allHours.map(h => bestHourSet.has(h) ? '#eab308' : 'rgba(234, 179, 8, 0.15)');

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels: allHours.map(h => h + ':00'),
            datasets: [{ data, backgroundColor: colors, borderRadius: 4 }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ctx.parsed.y.toFixed(2) + '% engagement' } } },
            scales: {
                y: { beginAtZero: true, ticks: { callback: v => v + '%' }, grid: { color: '#1f2937' } },
                x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 12 } },
            },
        }
    });
}

function renderTrendChart(trend) {
    const canvas = document.getElementById('trendChart');
    if (!canvas || !trend.length) return;

    const isDown = trend.length >= 2 && trend[trend.length - 1].avg_engagement < trend[0].avg_engagement;
    const color = isDown ? '#ef4444' : '#22c55e';

    new Chart(canvas, {
        type: 'line',
        data: {
            labels: trend.map(t => t.month),
            datasets: [{
                data: trend.map(t => t.avg_engagement),
                borderColor: color,
                backgroundColor: color + '20',
                fill: true, tension: 0.3, pointRadius: 4, pointBackgroundColor: color,
            }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ctx.parsed.y.toFixed(2) + '% engagement' } } },
            scales: {
                y: { beginAtZero: true, ticks: { callback: v => v + '%' }, grid: { color: '#1f2937' } },
                x: { grid: { display: false } },
            },
        }
    });
}

function renderTypeChart(typePerf) {
    const canvas = document.getElementById('typeChart');
    if (!canvas || !Object.keys(typePerf).length) return;

    const typeLabels = { GraphImage: 'Images', GraphVideo: 'Videos', GraphSidecar: 'Carousels' };
    const labels = Object.keys(typePerf).map(k => typeLabels[k] || k);
    const engagements = Object.values(typePerf).map(v => v.avg_engagement_rate);
    const colors = ['#3b82f6', '#8b5cf6', '#ec4899', '#f97316'];

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{ data: engagements, backgroundColor: colors.slice(0, labels.length), borderRadius: 6 }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: { legend: { display: false }, tooltip: { callbacks: { label: ctx => ctx.parsed.y.toFixed(2) + '% engagement' } } },
            scales: {
                y: { beginAtZero: true, ticks: { callback: v => v + '%' }, grid: { color: '#1f2937' } },
                x: { grid: { display: false } },
            },
        }
    });

    // Details cards
    document.getElementById('typeDetails').innerHTML = Object.entries(typePerf).map(([k, v]) => `
        <div class="bg-dark-900 rounded-lg p-3 text-center">
            <div class="text-xs text-gray-500 mb-1">${typeLabels[k] || k}</div>
            <div class="text-sm font-semibold text-white">${v.count} posts</div>
            <div class="text-xs text-gray-400">${v.avg_likes} avg likes</div>
        </div>
    `).join('');
}

function renderCaptionChart(captionPerf) {
    const canvas = document.getElementById('captionChart');
    if (!canvas || !Object.keys(captionPerf).length) return;

    const bucketLabels = { short: '0-50', medium: '51-150', long: '151-300', very_long: '300+' };
    const order = ['short', 'medium', 'long', 'very_long'];
    const labels = order.map(k => bucketLabels[k]);
    const data = order.map(k => captionPerf[k]?.avg_engagement || 0);
    const counts = order.map(k => captionPerf[k]?.post_count || 0);

    const maxVal = Math.max(...data);
    const colors = data.map(v => v === maxVal && v > 0 ? '#eab308' : 'rgba(234, 179, 8, 0.3)');

    new Chart(canvas, {
        type: 'bar',
        data: {
            labels,
            datasets: [{ data, backgroundColor: colors, borderRadius: 6 }]
        },
        options: {
            responsive: true, maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: { callbacks: { label: ctx => `${ctx.parsed.y.toFixed(2)}% eng (${counts[ctx.dataIndex]} posts)` } },
            },
            scales: {
                y: { beginAtZero: true, ticks: { callback: v => v + '%' }, grid: { color: '#1f2937' } },
                x: { grid: { display: false }, title: { display: true, text: 'Caption length (chars)', color: '#6b7280' } },
            },
        }
    });
}

function renderHashtagPerformance(hashPerf) {
    const topEl = document.getElementById('topHashtags');
    const bottomEl = document.getElementById('bottomHashtags');

    const topTags = hashPerf.top || [];
    const bottomTags = hashPerf.bottom || [];

    if (topEl) {
        const maxEng = topTags.length ? topTags[0].avg_engagement : 1;
        topEl.innerHTML = topTags.map(t => `
            <div class="flex items-center gap-3">
                <div class="flex-1">
                    <div class="flex items-center justify-between mb-1">
                        <span class="text-sm text-green-400">#${t.hashtag}</span>
                        <span class="text-xs text-gray-500">${t.avg_engagement.toFixed(2)}% &middot; ${t.post_count} posts</span>
                    </div>
                    <div class="h-1.5 bg-dark-900 rounded-full overflow-hidden">
                        <div class="h-full bg-green-500/60 rounded-full" style="width: ${Math.max(5, (t.avg_engagement / maxEng) * 100)}%"></div>
                    </div>
                </div>
            </div>
        `).join('') || '<p class="text-gray-600 text-sm">No hashtag data</p>';
    }

    if (bottomEl) {
        bottomEl.innerHTML = bottomTags.map(t => `
            <div class="flex items-center gap-3">
                <div class="flex-1">
                    <div class="flex items-center justify-between mb-1">
                        <span class="text-sm text-red-400">#${t.hashtag}</span>
                        <span class="text-xs text-gray-500">${t.avg_engagement.toFixed(2)}% &middot; ${t.post_count} posts</span>
                    </div>
                </div>
            </div>
        `).join('') || '<p class="text-gray-600 text-sm">Not enough data</p>';
    }
}

function renderCorrelation(correlations) {
    const section = document.getElementById('correlationSection');
    const list = document.getElementById('correlationList');
    if (!section || !list || !correlations || !correlations.length) return;

    section.classList.remove('hidden');
    list.innerHTML = correlations.map(c => {
        const changeColor = c.follower_change >= 0 ? 'text-green-400' : 'text-red-400';
        const changeIcon = c.follower_change >= 0 ? '+' : '';
        const correlated = c.high_engagement_correlated_with_growth;
        const badge = correlated
            ? '<span class="px-2 py-0.5 bg-green-500/10 text-green-400 rounded text-xs">Correlated</span>'
            : '';

        return `
            <div class="bg-dark-900 rounded-xl p-4 flex items-center justify-between gap-4">
                <div>
                    <div class="text-sm text-gray-300">${c.period_start} &rarr; ${c.period_end}</div>
                    <div class="text-xs text-gray-500">${c.posts_in_period} posts &middot; ${c.avg_engagement_in_period.toFixed(2)}% avg engagement</div>
                </div>
                <div class="flex items-center gap-3">
                    ${badge}
                    <div class="${changeColor} font-bold text-lg">${changeIcon}${c.follower_change}</div>
                </div>
            </div>
        `;
    }).join('');
}
