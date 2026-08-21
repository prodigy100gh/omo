document.addEventListener("DOMContentLoaded", function() {
    const filterBox = document.getElementById('changelist-filter');
    if (filterBox) {
        const header = filterBox.querySelector('h2');
        
        // 제목을 클릭하면 collapsed 클래스를 토글
        header.addEventListener('click', function() {
            filterBox.classList.toggle('collapsed');
        });
        
        // 처음부터 접혀있길 원한다면 아래 주석을 해제하세요.
        // filterBox.classList.add('collapsed'); 
    }
});