
const $ = (id) => document.getElementById(id);

let currentUser = null;
let currentPollId = null;
let currentPoll = null;
let resultsTimer = null;
let pollListTimer = null;


// Flask API 요청
async function api(path, method = "GET", data = null) {
    const options = {
        method,
        credentials: "same-origin"
    };

    if (data !== null) {
        options.headers = {
            "Content-Type": "application/json"
        };
        options.body = JSON.stringify(data);
    }

    const response = await fetch("/api" + path, options);

    const result = await response.json();

    if (!response.ok) {
        throw new Error(result.error || "요청에 실패했습니다.");
    }

    return result;
}



function showNotice(message, error = false) {
    const notice = $("notice");

    notice.textContent = message;
    notice.classList.toggle("error", error);
    notice.classList.remove("hidden");

    // 알림이 보이는 위치로 화면 이동
    notice.scrollIntoView({
        behavior: "smooth",
        block: "center"
    });
}



// 로그인 / 회원가입 탭 전환
function showAuthTab(tab) {
    const login = tab === "login";

    $("login-form").classList.toggle("hidden", !login);
    $("register-form").classList.toggle("hidden", login);

    $("login-tab").classList.toggle("active", login);
    $("register-tab").classList.toggle("active", !login);
}


// 로그인 화면 표시
function showLogin() {
    currentUser = null;
    currentPoll = null;
    currentPollId = null;

    clearInterval(resultsTimer);
    clearInterval(pollListTimer);

    $("auth-section").classList.remove("hidden");
    $("dashboard").classList.add("hidden");
    $("user-menu").classList.add("hidden");
    $("detail-section").classList.add("hidden");

    showAuthTab("login");
}


// 로그인 후 메인 화면
async function showDashboard(user) {
    currentUser = user;

    $("auth-section").classList.add("hidden");
    $("dashboard").classList.remove("hidden");
    $("user-menu").classList.remove("hidden");

    $("nickname").textContent = user.nickname;
    $("user-name").textContent = user.nickname;
    $("department-name").textContent = user.department;

    $("my-dept-option").value = user.department;
    $("my-dept-option").textContent =
        user.department + " 학생만";

    await loadPolls();

    clearInterval(pollListTimer);

    // 10초마다 목록 갱신
    pollListTimer = setInterval(() => {
        loadPolls(true).catch(console.error);
    }, 10000);
}


// 회원가입
$("register-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    const data = {
        username: $("register-username").value.trim(),
        password: $("register-password").value,
        nickname: $("register-nickname").value.trim(),
        department: $("register-department").value
    };

    try {
        await api("/register", "POST", data);

        showAuthTab("login");
        $("login-username").value = data.username;
        $("register-password").value = "";

        showNotice("회원가입 성공! 로그인해 주세요.");
    } catch (error) {
        showNotice(error.message, true);
    }
});


// 로그인
$("login-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    const data = {
        username: $("login-username").value.trim(),
        password: $("login-password").value
    };

    try {
        await api("/login", "POST", data);

        $("login-password").value = "";

        // 서버 세션에서 회원 정보 확인
        const user = await api("/me");

        $("notice").classList.add("hidden");
        await showDashboard(user);
    } catch (error) {
        showNotice(error.message, true);
    }
});


// 로그아웃
$("logout-btn").addEventListener("click", async () => {
    try {
        await api("/logout", "POST");

        showLogin();
        showNotice("로그아웃되었습니다.");
    } catch (error) {
        showNotice(error.message, true);
    }
});


// 투표 날짜 표시
function formatDate(value) {
    const date = new Date(value);

    if (Number.isNaN(date.getTime())) {
        return "날짜 확인 필요";
    }

    return date.toLocaleString("ko-KR", {
        timeZone: "Asia/Seoul",
        dateStyle: "medium",
        timeStyle: "short"
    });
}


// 기존 데이터의 시간대 없는 날짜는 한국 시간으로 해석
function deadlineDate(value) {
    const normalized = /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
        ? value
        : value + "+09:00";

    return new Date(normalized);
}


// 투표 목록 불러오기
async function loadPolls(silent = false) {
    try {
        const polls = await api("/polls");
        const list = $("poll-list");

        list.replaceChildren();

        if (polls.length === 0) {
            const empty = document.createElement("p");
            empty.textContent = "참여 가능한 투표가 없습니다.";
            list.appendChild(empty);
            return;
        }

        for (const poll of polls) {
            const card = document.createElement("button");
            card.type = "button";
            card.className = "poll-card";

            const badge = document.createElement("span");
            badge.className = "badge";
            badge.textContent = poll.target_department
                ? poll.target_department + " 전용"
                : "전체 학생";

            const title = document.createElement("h4");
            title.textContent = poll.title;

            const date = document.createElement("p");
            date.className = "muted";
            date.textContent = "마감: " + formatDate(
                deadlineDate(poll.deadline).toISOString()
            );

            const closed = Date.now() >=
                deadlineDate(poll.deadline).getTime();

            if (closed) {
                badge.textContent += " · 마감";
                badge.classList.add("closed");
            }

            card.append(badge, title, date);

            card.addEventListener("click", () => {
                openPoll(poll.id).catch((error) => {
                    showNotice(error.message, true);
                });
            });

            list.appendChild(card);
        }
    } catch (error) {
        if (!silent) showNotice(error.message, true);
        throw error;
    }
}


// 투표 생성 화면
$("show-create-btn").addEventListener("click", () => {
    $("create-section").classList.toggle("hidden");
});

$("cancel-create-btn").addEventListener("click", () => {
    $("create-section").classList.add("hidden");
});

$("add-option-btn").addEventListener("click", () => {
    const inputs = document.querySelectorAll(".poll-option");

    if (inputs.length >= 10) {
        showNotice("선택지는 최대 10개까지 가능합니다.", true);
        return;
    }

    const input = document.createElement("input");
    input.className = "poll-option";
    input.placeholder = "선택지 " + (inputs.length + 1);
    input.required = true;

    $("option-inputs").appendChild(input);
});


// 새 투표 생성
$("create-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    const options = Array.from(
        document.querySelectorAll(".poll-option")
    ).map((input) => input.value.trim());

    const data = {
        title: $("poll-title").value.trim(),
        deadline: $("poll-deadline").value,
        target_department: $("poll-target").value || null,
        options
    };

    try {
        await api("/polls", "POST", data);

        $("create-form").reset();

        $("option-inputs").replaceChildren();

        for (let i = 1; i <= 2; i++) {
            const input = document.createElement("input");
            input.className = "poll-option";
            input.placeholder = "선택지 " + i;
            input.required = true;
            $("option-inputs").appendChild(input);
        }

        $("create-section").classList.add("hidden");

        await loadPolls();
        showNotice("투표가 생성되었습니다.");
    } catch (error) {
        showNotice(error.message, true);
    }
});


// 투표 상세 열기
async function openPoll(pollId) {
    const data = await api("/polls/" + pollId + "/options");

    currentPollId = pollId;
    currentPoll = data.poll;

    $("detail-title").textContent = data.poll.title;
    $("detail-info").textContent =
        "마감: " + formatDate(
            deadlineDate(data.poll.deadline).toISOString()
        );

    const container = $("vote-options");
    container.replaceChildren();

    for (const option of data.options) {
        const label = document.createElement("label");
        label.className = "vote-option";

        const radio = document.createElement("input");
        radio.type = "radio";
        radio.name = "vote-option";
        radio.value = option.id;

        const text = document.createTextNode(option.content);

        label.append(radio, text);
        container.appendChild(label);
    }

    $("detail-section").classList.remove("hidden");

    updateDeadlineState();

    clearInterval(resultsTimer);

    await loadResults();

    // 결과는 3초마다 다시 조회
    resultsTimer = setInterval(() => {
        loadResults().catch(console.error);
        updateDeadlineState();
    }, 3000);

    $("detail-section").scrollIntoView({
        behavior: "smooth"
    });
}


// 마감 여부 표시
function updateDeadlineState() {
    if (!currentPoll) return;

    const closed = Date.now() >=
        deadlineDate(currentPoll.deadline).getTime();

    $("vote-btn").disabled = closed;
    $("vote-btn").textContent = closed
        ? "마감된 투표입니다"
        : "투표하기";
}


// 투표 참여
$("vote-form").addEventListener("submit", async (event) => {
    event.preventDefault();

    if (currentPollId === null) return;

    const selected = document.querySelector(
        'input[name="vote-option"]:checked'
    );

    if (!selected) {
        showNotice("선택지를 선택해 주세요.", true);
        return;
    }

    try {
        await api(
            "/polls/" + currentPollId + "/vote",
            "POST",
            {option_id: Number(selected.value)}
        );

        showNotice("투표가 완료되었습니다.");
        await loadResults();
    } catch (error) {
        showNotice(error.message, true);
    }
});


// 결과 조회
async function loadResults() {
    if (currentPollId === null) return;

    const pollId = currentPollId;
    const data = await api("/polls/" + pollId + "/results");

    if (currentPollId !== pollId) return;

    $("total-votes").textContent =
        "총 " + data.total_votes + "표";

    const container = $("results-list");
    container.replaceChildren();

    for (const result of data.results) {
        const item = document.createElement("div");
        item.className = "result-item";

        const info = document.createElement("div");
        info.className = "result-info";

        const name = document.createElement("span");
        name.textContent = result.content;

        const count = document.createElement("span");
        count.textContent =
            result.votes + "표 (" + result.percentage + "%)";

        info.append(name, count);

        const progress = document.createElement("div");
        progress.className = "progress";

        const bar = document.createElement("div");
        bar.className = "progress-bar";
        bar.style.width = result.percentage + "%";

        progress.appendChild(bar);
        item.append(info, progress);
        container.appendChild(item);
    }
}


// 목록으로 이동
$("back-btn").addEventListener("click", () => {
    clearInterval(resultsTimer);

    currentPollId = null;
    currentPoll = null;

    $("detail-section").classList.add("hidden");
});

$("refresh-btn").addEventListener("click", () => {
    loadPolls().catch(console.error);
});

$("login-tab").addEventListener("click", () => {
    showAuthTab("login");
});

$("register-tab").addEventListener("click", () => {
    showAuthTab("register");
});


// 페이지 처음 열 때 로그인 상태 확인
async function initialize() {
    try {
        const user = await api("/me");
        await showDashboard(user);
    } catch {
        showLogin();
    }
}

initialize();
