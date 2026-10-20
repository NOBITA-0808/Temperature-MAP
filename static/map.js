
        const COLORS = ["#2878d0", "#e74c67", "#f39c35", "#34a853", "#8e5cc7", "#00a6a6", "#795548", "#607d8b"];
        const map = L.map("map").setView([37, 137], 5);
        let hasFitted = false;
        L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">OpenStreetMap</a> contributors',
            maxZoom: 19
        }).addTo(map);

        let latest = [];
        let selectedDevice = null;
        const markerByDevice = new Map();
        let detailChart = null;
        let compareChart = null;

        const formatValue = (value, digits = 2) =>
            value == null ? "－" : Number(value).toFixed(digits);

        function formatTime(value) {
            if (!value) return "－";
            const date = new Date(value);
            return Number.isNaN(date.getTime()) ? value : date.toLocaleString("ja-JP", {timeZone:"Asia/Tokyo"});
        }

        function escapeHtml(value) {
            return String(value ?? "").replace(/[&<>'"]/g, char => ({
                "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;"
            })[char]);
        }

        async function fetchJson(url, options) {
            const response = await fetch(url, options);
            if (response.status === 401) { location.href='/login'; throw new Error('ログインが必要です'); }
            if (!response.ok) { let message = `${response.status} ${response.statusText}`; try { message=(await response.json()).error || message; } catch {} throw new Error(message); }
            return response.json();
        }

        function renderTable() {
            const body = document.getElementById("latestBody");
            body.innerHTML = "";
            document.getElementById("emptyMessage").hidden = latest.length !== 0;

            latest.forEach(item => {
                const row = document.createElement("tr");
                row.dataset.device = item.name;
                row.classList.toggle("selected", item.name === selectedDevice);
                row.innerHTML = `
                    <td><strong>${escapeHtml(item.display_name || item.name)}</strong><span class="device-id">${escapeHtml(item.name)}</span></td>
                    <td>${formatValue(item.temp)}</td>
                    <td>${formatValue(item.hum)}</td>
                    <td>${formatValue(item.press)}</td>
                    <td>${escapeHtml(formatTime(item.recorded_at))}</td>
                `;
                row.addEventListener("click", () => selectDevice(item.name, true));
                body.appendChild(row);
            });
        }

        function renderMarkers() {
            markerByDevice.forEach(marker => map.removeLayer(marker));
            markerByDevice.clear();
            const bounds = [];

            latest.forEach(item => {
                if (item.lat == null || item.lng == null) return;
                const marker = L.marker([item.lat, item.lng]).addTo(map);
                const label = escapeHtml(item.display_name || item.name);
                marker.bindPopup(
                    `<b>${label}</b><br>` +
                    `気温: ${formatValue(item.temp)} ℃<br>` +
                    `湿度: ${formatValue(item.hum)} %<br>` +
                    `気圧: ${formatValue(item.press)} hPa`
                );
                marker.bindTooltip(`${label}<br>${formatValue(item.temp, 1)}℃`, {
                    permanent: true, direction: "top", offset: [0, -10], className: "my-label"
                });
                marker.on("click", () => selectDevice(item.name, false));
                markerByDevice.set(item.name, marker);
                bounds.push([item.lat, item.lng]);
            });

            if (!hasFitted && bounds.length === 1) map.setView(bounds[0], 14);
            if (!hasFitted && bounds.length > 1) map.fitBounds(bounds, {padding: [40, 40], maxZoom: 14});
            if (bounds.length) hasFitted = true;
        }

        async function selectDevice(deviceId, openPopup) {
            selectedDevice = deviceId;
            renderTable();
            const selected = latest.find(item => item.name === deviceId);
            if (selected) document.getElementById("detailTitle").textContent = `${selected.display_name || selected.name} の${periodLabel()}グラフ`;
            if (openPopup && markerByDevice.has(deviceId)) markerByDevice.get(deviceId).openPopup();
            await loadDetailChart(deviceId);
        }

        function commonChartOptions(yTitle) {
            return {
                responsive: true,
                locale: "ja-JP",
                maintainAspectRatio: false,
                interaction: {mode: "nearest", intersect: false},
                scales: {
                    x: {type: "time", adapters: {date:{zone:"Asia/Tokyo",locale:"ja"}}, time: {tooltipFormat: "yyyy/LL/dd HH:mm", displayFormats: {hour: "HH:mm", minute: "HH:mm", second:"HH:mm:ss", millisecond:"HH:mm:ss.SSS"}}, title: {display: true, text: "時刻"}},
                    y: {title: {display: true, text: yTitle}}
                },
                plugins: {legend: {position: "top"}}
            };
        }

        async function loadDetailChart(deviceId) {
            const history = await fetchJson(`/history?name=${encodeURIComponent(deviceId)}&${filterQuery()}`);
            const datasets = [
                {label: "気温 ℃", data: history.map(p => ({x: p.recorded_at, y: p.temp})), borderColor: "#2878d0", backgroundColor: "#2878d022", yAxisID: "y", tension: .25},
                {label: "湿度 %", data: history.map(p => ({x: p.recorded_at, y: p.hum})), borderColor: "#e74c67", backgroundColor: "#e74c6722", yAxisID: "y", tension: .25},
                {label: "気圧 hPa", data: history.map(p => ({x: p.recorded_at, y: p.press})), borderColor: "#f39c35", backgroundColor: "#f39c3522", yAxisID: "pressure", tension: .25}
            ];

            if (selectedDevice !== deviceId) return;
            if (detailChart) detailChart.destroy();
            detailChart = new Chart(document.getElementById("detailChart"), {
                type: "line",
                data: {datasets},
                options: {
                    ...commonChartOptions("気温（℃）・湿度（%）"),
                    scales: {
                        x: commonChartOptions("").scales.x,
                        y: {position: "left", title: {display: true, text: "気温（℃）・湿度（%）"}},
                        pressure: {position: "right", grid: {drawOnChartArea: false}, title: {display: true, text: "気圧（hPa）"}}
                    }
                }
            });
        }

        async function loadCompareChart() {
            const series = await fetchJson(`/compare?${filterQuery()}`);
            const datasets = series.map((item, index) => ({
                label: item.display_name || item.name,
                data: item.points.map(point => ({x: point.recorded_at, y: point.temp})),
                borderColor: COLORS[index % COLORS.length],
                backgroundColor: COLORS[index % COLORS.length] + "22",
                pointRadius: 1.8,
                borderWidth: 2,
                tension: .2
            }));

            if (compareChart) compareChart.destroy();
            compareChart = new Chart(document.getElementById("compareChart"), {
                type: "line",
                data: {datasets},
                options: commonChartOptions("気温（℃）")
            });
        }

        async function loadAll() {
            const status = document.getElementById("statusText");
            try {
                status.textContent = "更新中…";
                latest = await fetchJson(`/latest?${filterQuery()}`);
                if (!latest.some(item => item.name === selectedDevice)) selectedDevice = latest[0]?.name || null;
                renderTable();
                renderMarkers();
                if (selectedDevice) await selectDevice(selectedDevice, false);
                else { if (detailChart) { detailChart.destroy(); detailChart=null; } document.getElementById('detailTitle').textContent='この期間の観測データはありません'; }
                await loadPhotos();
                document.getElementById('compareTitle').textContent=`全地点の気温比較（${periodLabel()}）`;
                document.getElementById('csvLink').href='/csv' + (filterDay() ? '?date='+filterDay() : '');
                await loadCompareChart();
                status.textContent = `最終更新: ${new Date().toLocaleTimeString("ja-JP")}`;
            } catch (error) {
                console.error(error);
                status.textContent = `読込エラー: ${error.message}`;
            }
        }

        document.getElementById("refreshButton").addEventListener("click", loadAll);

    
const el = id => document.getElementById(id);
const filterDay = () => el('filterDate').value;
const filterQuery = () => filterDay() ? 'date='+encodeURIComponent(filterDay()) : 'hours=24';
const periodLabel = () => filterDay() || '過去24時間';
const csrf = document.querySelector('meta[name=csrf-token]').content;
const jstInput = value => new Date(new Date(value).getTime()+9*3600*1000).toISOString().slice(0,16);
const photoLayer = L.markerClusterGroup({maxClusterRadius:60, showCoverageOnHover:false});
map.addLayer(photoLayer);
let editingPhoto = null, picking = false, selectedLocation = null, editorGeneration = 0;

function pickStop() {
    picking=false; el('pickStatus').hidden=true; map.getContainer().style.cursor='';
}
function resetPhoto() {
    editorGeneration++;
    editingPhoto=null; el('photoForm').reset(); el('photoInput').required=true;
    el('photoInput').disabled=false; el('photoEditorTitle').textContent='写真を登録する';
    el('savePhoto').textContent='登録する'; el('metadataStatus').textContent='';
    el('photoStatus').textContent=''; pickStop();
    if (selectedLocation) {map.removeLayer(selectedLocation); selectedLocation=null;}
}
el('cancelPhoto').onclick=resetPhoto;
el('pickLocation').onclick=()=>{
    picking=!picking; el('pickStatus').hidden=!picking;
    map.getContainer().style.cursor=picking?'crosshair':'';
    if(picking) map.getContainer().scrollIntoView({behavior:'smooth',block:'center'});
};
map.on('click',e=>{
    if(!picking) return;
    el('photoLat').value=e.latlng.lat.toFixed(6); el('photoLng').value=e.latlng.lng.toFixed(6);
    if(selectedLocation) map.removeLayer(selectedLocation);
    selectedLocation=L.circleMarker(e.latlng,{radius:10,color:'#c63d58'}).addTo(map);
    pickStop(); el('photoStatus').textContent='場所を設定しました。撮影日時と説明を確認して保存してください。';
});
el('photoInput').onchange=async()=>{
    const file=el('photoInput').files[0]; if(!file) return;
    const generation=++editorGeneration;
    const form=new FormData(); form.append('photo',file);
    el('savePhoto').disabled=true;
    el('metadataStatus').textContent='GPS・撮影日時を読み取り中…';
    try{
        const meta=await fetchJson('/api/photos/metadata',{method:'POST',headers:{'X-CSRF-Token':csrf},body:form});
        if(generation!==editorGeneration) return;
        el('photoLat').value=meta.lat??''; el('photoLng').value=meta.lng??'';
        el('photoTime').value=meta.taken_at?jstInput(meta.taken_at):'';
        el('metadataStatus').textContent=(meta.lat==null?'GPSなし：地図で場所を指定してください。':'GPSを読み取りました。')+' '+(meta.taken_at?meta.time_source+'。日時を確認してください。':'撮影日時を入力してください。');
    }catch(error){if(generation===editorGeneration) el('metadataStatus').textContent=error.message;}
    finally{el('savePhoto').disabled=false;}
};
el('photoForm').onsubmit=async e=>{
    e.preventDefault();
    el('savePhoto').disabled=true;
    const form=new FormData(el('photoForm'));
    // Explicit UTC offset prevents browser/server timezone from shifting a Japanese wall clock value.
    form.set('taken_at',el('photoTime').value+':00+09:00');
    try{
        await fetchJson(editingPhoto?`/api/photos/${editingPhoto}/edit`:'/api/photos',{
            method:'POST',headers:{'X-CSRF-Token':csrf},body:form});
        resetPhoto(); el('photoStatus').textContent='保存しました。'; await loadPhotos();
    }catch(error){el('photoStatus').textContent=error.message;}
    finally{el('savePhoto').disabled=false;}
};
async function loadPhotos(){
    photoLayer.clearLayers(); el('photoGallery').replaceChildren();
    let offset=0,count=0;
    // Sequential pages ensure the whole class collection is shown, rather than silently truncating.
    do{
        const page=await fetchJson(`/api/photos?offset=${offset}${filterDay()?'&date='+filterDay():''}`);
        for(const photo of page.items){
            const icon=document.createElement('div');
            const img=document.createElement('img'); img.src=photo.thumbnail_url; img.alt='写真'; icon.append(img);
            L.marker([photo.lat,photo.lng],{icon:L.divIcon({className:'photo-icon',html:icon.innerHTML,iconSize:[48,48]})})
                .on('click',()=>openPhoto(photo.id).catch(showError)).addTo(photoLayer);
            const button=document.createElement('button'); button.type='button';
            const thumb=document.createElement('img'); thumb.src=photo.thumbnail_url; thumb.alt=photo.description||'登録写真'; thumb.loading='lazy';
            const caption=document.createElement('small'); caption.textContent=photo.description||photo.username;
            button.append(thumb,caption); button.onclick=()=>openPhoto(photo.id).catch(showError); el('photoGallery').append(button); count++;
        }
        offset=page.next_offset;
    }while(offset!==null);
    el('photoCount').textContent=`（${count}枚）`;
    if(count===0) el('photoGallery').textContent='この表示条件の写真はありません。';
}
function showError(error){el('statusText').textContent='エラー：'+error.message;}
async function openPhoto(id){
    const p=await fetchJson('/api/photos/'+id);
    el('photoHeading').textContent='写真 · '+p.username; el('fullPhoto').src=p.url;
    el('photoDescription').textContent=p.description||'説明なし';
    el('photoInfo').textContent=`撮影：${formatTime(p.taken_at)}（日本時間）／緯度 ${p.lat}・経度 ${p.lng}／${p.time_source}`;
    const obs=p.observation;
    el('photoWeather').textContent=obs?`近隣の観測値：気温 ${formatValue(obs.temp)} ℃・湿度 ${formatValue(obs.hum)} %・気圧 ${formatValue(obs.press)} hPa。地点：${obs.display_name}、記録：${formatTime(obs.recorded_at)}。写真の場所から約${obs.distance_m}m、撮影との時間差${obs.time_diff_minutes}分。`:'撮影場所から5km以内・撮影前後60分以内の観測データはありません。';
    el('photoActions').replaceChildren();
    if(obs){
        const b=document.createElement('button'); b.textContent='この観測地点のグラフ';
        b.onclick=async()=>{el('photoDialog').close();el('filterDate').value=jstInput(obs.recorded_at).slice(0,10);await loadAll();await selectDevice(obs.device_name,true);};
        el('photoActions').append(b);
    }
    if(p.can_edit){
        const b=document.createElement('button'); b.textContent='説明・場所・日時を編集';
        b.onclick=()=>{
            resetPhoto(); editingPhoto=p.id; el('photoDialog').close(); el('photoEditor').open=true;
            el('photoInput').disabled=true; el('photoInput').required=false;
            el('photoForm').elements.description.value=p.description;
            el('photoLat').value=p.lat;el('photoLng').value=p.lng;el('photoTime').value=jstInput(p.taken_at);
            el('photoEditorTitle').textContent='写真を編集する'; el('savePhoto').textContent='変更を保存';
            el('photoEditor').scrollIntoView({behavior:'smooth'});
        }; el('photoActions').append(b);
    }
    if(IS_ADMIN){
        const b=document.createElement('button');b.textContent='ごみ箱へ移動';b.className='danger';
        b.onclick=async()=>{
            if(!confirm('この写真をごみ箱へ移動しますか？管理画面から復元できます。'))return;
            try{const f=new FormData();f.set('confirm','yes');await fetchJson(`/admin/photos/${p.id}/trash`,{method:'POST',headers:{'X-CSRF-Token':csrf},body:f});el('photoDialog').close();await loadPhotos();}catch(error){alert(error.message);}
        };el('photoActions').append(b);
    }
    el('photoDialog').showModal();
}
el('closePhoto').onclick=()=>el('photoDialog').close();
el('filterDate').onchange=()=>loadAll();
el('resetDate').onclick=()=>{el('filterDate').value='';loadAll();};
resetPhoto();loadAll();setInterval(loadAll,5*60*1000);
