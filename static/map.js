
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
        const observationLayer = L.layerGroup().addTo(map);
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
            observationLayer.clearLayers();
            markerByDevice.clear();
            const bounds = [];

            latest.forEach(item => {
                if (item.lat == null || item.lng == null) return;
                const marker = L.marker([item.lat, item.lng]).addTo(observationLayer);
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
            el("showObservationLocations").disabled = bounds.length === 0;
        }

        async function selectDevice(deviceId, openPopup) {
            selectedDevice = deviceId;
            renderTable();
            const selected = latest.find(item => item.name === deviceId);
            if (selected) document.getElementById("detailTitle").textContent = `${selected.display_name || selected.name} の${periodLabel()}グラフ`;
            if (openPopup && markerByDevice.has(deviceId)) {
                map.addLayer(observationLayer);
                const marker = markerByDevice.get(deviceId);
                map.setView(marker.getLatLng(), 14, {animate:false});
                marker.openPopup();
            }
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
const markerByPhoto = new Map();
let photoBounds = [];
L.control.layers(null, {'観測地点':observationLayer,'写真の撮影場所':photoLayer},
                 {collapsed:false,position:'topright'}).addTo(map);

function fitLocations(points, layer, emptyMessage) {
    if (!points.length) { el('statusText').textContent=emptyMessage; return; }
    map.addLayer(layer);
    map.invalidateSize();
    if(points.length===1) map.setView(points[0],14,{animate:false});
    else map.fitBounds(points,{padding:[50,50],maxZoom:14,animate:false});
    hasFitted=true;
    el('map').scrollIntoView({behavior:'smooth',block:'center'});
}
function focusPhotoLocation(photo) {
    map.addLayer(photoLayer);
    map.invalidateSize();
    map.setView([photo.lat,photo.lng],14,{animate:false});
    hasFitted=true;
    const marker=markerByPhoto.get(photo.id);
    if(marker) photoLayer.zoomToShowLayer(marker,()=>marker.openTooltip());
    el('map').scrollIntoView({behavior:'smooth',block:'center'});
}
el('showPhotoLocations').onclick=()=>fitLocations(photoBounds,photoLayer,'この表示条件の写真はありません。');
el('showObservationLocations').onclick=()=>fitLocations(
    latest.filter(p=>p.lat!=null&&p.lng!=null).map(p=>[p.lat,p.lng]),
    observationLayer,'この期間に位置情報のある観測データはありません。');
let editingPhoto = null, picking = false, selectedLocation = null, editorGeneration = 0;
const MAX_BATCH_PHOTOS = 10;
let photoQueue = [], activeQueueIndex = -1, metadataReading = false, batchSubmitting = false;
const draftFields = () => [el('photoLat'),el('photoLng'),el('photoTime'),el('photoForm').elements.description];
const jstTimestamp = value => (value.length===16 ? value+':00' : value)+'+09:00';

function pickStop() {
    picking=false; el('pickStatus').hidden=true; map.getContainer().style.cursor='';
}
function draftIssues(item) {
    if(item.metadataError) return '写真の読取を再試行するか、選択から外してください。';
    if(item.lat==='' || item.lng==='' || !Number.isFinite(Number(item.lat)) || !Number.isFinite(Number(item.lng)) ||
       Number(item.lat)<-90 || Number(item.lat)>90 || Number(item.lng)<-180 || Number(item.lng)>180)
        return '撮影場所を指定してください。';
    if(!item.takenAt || !Number.isFinite(Date.parse(jstTimestamp(item.takenAt)))) return '撮影日時を指定してください。';
    if(item.description.length>1000) return '説明は1000文字以内にしてください。';
    return '';
}
function saveActiveDraft() {
    const item=photoQueue[activeQueueIndex];
    if(!item || item.saved || metadataReading || batchSubmitting || editingPhoto) return;
    item.lat=el('photoLat').value; item.lng=el('photoLng').value; item.takenAt=el('photoTime').value;
    item.description=el('photoForm').elements.description.value;
}
function setEditorControls() {
    const busy=metadataReading||batchSubmitting;
    const selected=photoQueue[activeQueueIndex];
    el('photoInput').disabled=busy||Boolean(editingPhoto);
    el('photoInput').required=false;
    for(const field of draftFields()) field.disabled=busy||Boolean(selected?.saved);
    el('pickLocation').disabled=busy||Boolean(selected?.saved);
    el('cancelPhoto').disabled=batchSubmitting;
    const pending=photoQueue.filter(item=>!item.saved).length;
    el('savePhoto').disabled=busy||(!editingPhoto && pending===0);
    el('savePhoto').textContent=editingPhoto?'変更を保存':pending>1?`まとめて登録（${pending}枚）`:pending===1?'登録する':photoQueue.length?'登録済み':'登録する';
}
function renderPhotoQueue() {
    const container=el('photoQueue'); container.replaceChildren(); container.hidden=photoQueue.length===0;
    photoQueue.forEach((item,index)=>{
        const row=document.createElement('div'); row.className='photo-queue-row';
        row.classList.toggle('selected',index===activeQueueIndex);
        const select=document.createElement('button'); select.type='button';
        select.textContent=`${index+1}. ${item.name}`; select.setAttribute('aria-pressed',String(index===activeQueueIndex));
        select.disabled=metadataReading||batchSubmitting;
        select.onclick=()=>{saveActiveDraft();selectQueuedPhoto(index);};
        const state=document.createElement('span'); state.className='photo-queue-status';state.setAttribute('role','status');
        state.textContent=item.saved?'登録済み':item.saving?'登録中…':item.reading?'読取中…':item.metadataError?'読取失敗：'+item.metadataError:
                          item.uploadError?'登録失敗：'+item.uploadError:draftIssues(item)?'場所・日時を確認':'登録できます';
        row.append(select,state);
        if(item.metadataError && !item.saved){
            const retry=document.createElement('button'); retry.type='button';retry.textContent='読取を再試行';
            retry.disabled=metadataReading||batchSubmitting;
            retry.onclick=()=>readQueueMetadata([index]);row.append(retry);
        }
        if(!item.saved){
            const remove=document.createElement('button');remove.type='button';remove.textContent='選択から外す';
            remove.disabled=metadataReading||batchSubmitting;
            remove.onclick=()=>{
                saveActiveDraft();photoQueue.splice(index,1);
                if(!photoQueue.length){resetPhoto();return;}
                selectQueuedPhoto(0);
            };row.append(remove);
        }
        container.append(row);
    });
    const saved=photoQueue.filter(item=>item.saved).length;
    const needs=photoQueue.filter(item=>!item.saved && !item.reading && draftIssues(item)).length;
    el('photoQueueSummary').textContent=photoQueue.length?`選択 ${photoQueue.length}枚 ／ 登録済み ${saved}枚${needs?` ／ 場所・日時などの確認が必要 ${needs}枚`:''}`:'';
    setEditorControls();
}
function selectQueuedPhoto(index) {
    pickStop(); activeQueueIndex=index;
    const item=photoQueue[index];
    el('activePhotoName').hidden=!item;
    if(item){
        el('activePhotoName').textContent='確認中：'+item.name;
        el('photoLat').value=item.lat;el('photoLng').value=item.lng;el('photoTime').value=item.takenAt;
        el('photoForm').elements.description.value=item.description;
        el('metadataStatus').textContent=item.metadataError?item.metadataError:
            (item.source||'撮影情報なし')+'。場所・日時・説明はこの写真だけに適用します。';
    }
    if(selectedLocation){map.removeLayer(selectedLocation);selectedLocation=null;}
    renderPhotoQueue();
}
function resetPhoto() {
    if(batchSubmitting) return;
    editorGeneration++;metadataReading=false;
    photoQueue=[];activeQueueIndex=-1;editingPhoto=null;el('photoForm').reset();
    el('photoEditorTitle').textContent='写真を登録する';el('metadataStatus').textContent='';
    el('photoStatus').textContent='';el('activePhotoName').hidden=true;pickStop();
    if(selectedLocation){map.removeLayer(selectedLocation);selectedLocation=null;}
    renderPhotoQueue();
}
if(IS_LOGGED_IN){
el('cancelPhoto').onclick=resetPhoto;
for(const field of draftFields()) field.addEventListener('input',()=>{saveActiveDraft();renderPhotoQueue();});
el('pickLocation').onclick=()=>{
    if(metadataReading||batchSubmitting) return;
    picking=!picking;el('pickStatus').hidden=!picking;
    map.getContainer().style.cursor=picking?'crosshair':'';
    if(picking) map.getContainer().scrollIntoView({behavior:'smooth',block:'center'});
};
map.on('click',e=>{
    if(!picking||metadataReading||batchSubmitting) return;
    el('photoLat').value=e.latlng.lat.toFixed(6);el('photoLng').value=e.latlng.lng.toFixed(6);
    saveActiveDraft();
    if(selectedLocation) map.removeLayer(selectedLocation);
    selectedLocation=L.circleMarker(e.latlng,{radius:10,color:'#c63d58'}).addTo(map);
    pickStop();renderPhotoQueue();el('photoStatus').textContent='選んでいる写真の場所を設定しました。撮影日時と説明も確認してください。';
});
async function readQueueMetadata(indices) {
    if(batchSubmitting||metadataReading) return;
    saveActiveDraft();const generation=++editorGeneration;
    metadataReading=true;pickStop();renderPhotoQueue();
    for(let count=0;count<indices.length;count++){
        if(generation!==editorGeneration) return;
        const item=photoQueue[indices[count]];
        if(!item||item.saved) continue;
        item.reading=true;item.metadataError='';renderPhotoQueue();
        el('metadataStatus').textContent=`GPS・撮影日時を読取中：${count+1}/${indices.length} ${item.name}`;
        try{
            if(item.file.size>=20*1024*1024) throw new Error('1枚20MB未満の写真を選んでください。');
            const form=new FormData();form.append('photo',item.file);
            const meta=await fetchJson('/api/photos/metadata',{method:'POST',headers:{'X-CSRF-Token':csrf},body:form});
            if(generation!==editorGeneration) return;
            item.lat=meta.lat==null?'':String(meta.lat);item.lng=meta.lng==null?'':String(meta.lng);
            item.takenAt=meta.taken_at?jstInput(meta.taken_at):'';
            item.source=(meta.lat==null?'GPSなし：地図で場所を指定してください':'GPS読取済み')+' ／ '+
                        (meta.taken_at?meta.time_source:'撮影日時を入力してください');
        }catch(error){if(generation===editorGeneration) item.metadataError=error.message;}
        finally{item.reading=false;}
    }
    if(generation!==editorGeneration) return;
    metadataReading=false;selectQueuedPhoto(activeQueueIndex>=0?activeQueueIndex:0);
    el('photoStatus').textContent='写真ごとの撮影情報を確認し、「登録する」または「まとめて登録」を押してください。';
}
el('photoInput').onchange=async()=>{
    const files=Array.from(el('photoInput').files);if(!files.length) return;
    if(files.length>MAX_BATCH_PHOTOS){resetPhoto();el('photoStatus').textContent=`1回に選べる写真は${MAX_BATCH_PHOTOS}枚までです。選び直してください。`;return;}
    editorGeneration++;editingPhoto=null;activeQueueIndex=-1;
    photoQueue=files.map(file=>({file,name:file.name,lat:'',lng:'',takenAt:'',description:'',source:'',
        metadataError:'',uploadError:'',saved:false,reading:true,token:crypto.randomUUID()}));
    el('photoStatus').textContent='';await readQueueMetadata(photoQueue.map((_,i)=>i));
};
el('photoForm').onsubmit=async e=>{
    e.preventDefault();if(metadataReading||batchSubmitting) return;
    if(editingPhoto){
        if(!el('photoForm').reportValidity()) return;
        const form=new FormData(el('photoForm'));form.set('taken_at',jstTimestamp(el('photoTime').value));
        batchSubmitting=true;setEditorControls();
        try{
            await fetchJson(`/api/photos/${editingPhoto}/edit`,{method:'POST',headers:{'X-CSRF-Token':csrf},body:form});
            batchSubmitting=false;resetPhoto();el('photoStatus').textContent='保存しました。';await loadPhotos();
        }catch(error){el('photoStatus').textContent=error.message;}
        finally{batchSubmitting=false;setEditorControls();}return;
    }
    saveActiveDraft();
    const pending=photoQueue.filter(item=>!item.saved);
    if(!pending.length){el('photoStatus').textContent='写真を選択してください。';return;}
    const invalid=photoQueue.findIndex(item=>!item.saved&&draftIssues(item));
    if(invalid>=0){selectQueuedPhoto(invalid);el('photoStatus').textContent=photoQueue[invalid].name+'：'+draftIssues(photoQueue[invalid]);return;}
    batchSubmitting=true;pickStop();renderPhotoQueue();
    let successes=0,failures=0;
    for(let index=0;index<pending.length;index++){
        const item=pending[index];item.saving=true;item.uploadError='';renderPhotoQueue();
        el('photoStatus').textContent=`登録中：${index+1}/${pending.length} ${item.name}（画面を閉じないでください）`;
        const form=new FormData();form.append('photo',item.file);form.set('lat',item.lat);form.set('lng',item.lng);
        form.set('taken_at',jstTimestamp(item.takenAt));form.set('description',item.description);form.set('upload_token',item.token);
        try{
            const result=await fetchJson('/api/photos',{method:'POST',headers:{'X-CSRF-Token':csrf},body:form});
            item.saved=true;item.id=result.id;item.file=null;successes++;
        }catch(error){item.uploadError=error.message;failures++;}
        finally{item.saving=false;renderPhotoQueue();}
    }
    batchSubmitting=false;renderPhotoQueue();
    const message=failures?`登録結果：成功 ${successes}枚 ／ 失敗 ${failures}枚。失敗した写真だけ再試行できます。`:
                           `保存しました：${successes}枚。続ける場合は別の写真を選んでください。`;
    el('photoStatus').textContent=message;
    if(photoQueue[activeQueueIndex]?.saved) setEditorControls();
    try{await loadPhotos();}catch(error){el('photoStatus').textContent=message+' 一覧の再読込に失敗しました。「最新データ更新」を押してください。';}
};
}
async function loadPhotos(){
    photoLayer.clearLayers(); markerByPhoto.clear(); photoBounds=[];
    el('showPhotoLocations').disabled=true; el('photoGallery').replaceChildren();
    let offset=0,count=0;
    // Sequential pages ensure the whole class collection is shown, rather than silently truncating.
    do{
        const page=await fetchJson(`/api/photos?offset=${offset}${filterDay()?'&date='+filterDay():''}`);
        for(const photo of page.items){
            const icon=document.createElement('div');
            const img=document.createElement('img'); img.src=photo.thumbnail_url; img.alt='写真'; icon.append(img);
            const marker=L.marker([photo.lat,photo.lng],{icon:L.divIcon({className:'photo-icon',html:icon.innerHTML,iconSize:[48,48]})})
                .bindTooltip(escapeHtml(photo.description||'写真')+'<br>'+escapeHtml(formatTime(photo.taken_at)))
                .on('click',()=>openPhoto(photo.id).catch(showError)).addTo(photoLayer);
            markerByPhoto.set(photo.id,marker); photoBounds.push([photo.lat,photo.lng]);
            const button=document.createElement('button'); button.type='button';
            const thumb=document.createElement('img'); thumb.src=photo.thumbnail_url; thumb.alt=photo.description||'登録写真'; thumb.loading='lazy';
            const caption=document.createElement('small'); caption.textContent=photo.description||photo.username;
            button.append(thumb,caption); button.onclick=()=>openPhoto(photo.id).catch(showError); el('photoGallery').append(button); count++;
        }
        offset=page.next_offset;
    }while(offset!==null);
    el('photoCount').textContent=`（${count}枚）`;
    el('showPhotoLocations').disabled=count===0;
    if(!hasFitted && count>0) fitLocations(photoBounds,photoLayer,'');
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
    const locationButton=document.createElement('button');
    locationButton.textContent='この写真の場所を地図で見る';
    locationButton.onclick=()=>{el('photoDialog').close();focusPhotoLocation(p);};
    el('photoActions').append(locationButton);
    if(obs){
        const b=document.createElement('button'); b.textContent='この観測地点のグラフ';
        b.onclick=async()=>{el('photoDialog').close();el('filterDate').value=jstInput(obs.recorded_at).slice(0,10);await loadAll();await selectDevice(obs.device_name,true);};
        el('photoActions').append(b);
    }
    if(p.can_edit){
        const b=document.createElement('button'); b.textContent='説明・場所・日時を編集';
        b.onclick=()=>{
            if(batchSubmitting){el('photoStatus').textContent='登録処理が完了してから編集してください。';return;}
            resetPhoto(); editingPhoto=p.id; el('photoDialog').close(); el('photoEditor').open=true;
            el('photoInput').disabled=true; el('photoInput').required=false;
            el('photoForm').elements.description.value=p.description;
            el('photoLat').value=p.lat;el('photoLng').value=p.lng;el('photoTime').value=jstInput(p.taken_at);
            el('photoEditorTitle').textContent='写真を編集する';setEditorControls();
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
if(IS_LOGGED_IN) resetPhoto();loadAll();setInterval(loadAll,5*60*1000);
