import { useState, useEffect, useRef } from 'react';
import { View, Text, ScrollView, StyleSheet, SafeAreaView, Platform, TouchableOpacity } from 'react-native';

if (Platform.OS === 'web' && typeof document !== 'undefined') {
  const l = document.createElement('link');
  l.href = 'https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&display=swap';
  l.rel = 'stylesheet';
  document.head.appendChild(l);
}

const C = { bg:'#09090b', t:'#f0eff4', m:'#52525b', d:'#27272a', g:'#16a34a', r:'#dc2626', p:'#9f7aea' };
const MONO = { fontFamily: "'IBM Plex Mono', monospace" };

const fmt = (o) => o == null ? '\u2014' : o > 0 ? '+'+o : ''+o;
const fmtPct = (n) => n == null ? '\u2014' : (n*100).toFixed(1)+'%';
const fmtEdge = (n) => n == null ? '\u2014' : (n>0?'+':'')+(n*100).toFixed(1)+'%';
const mlToImp = (ml) => { if (ml==null) return null; const m=parseFloat(ml); return m<0 ? Math.abs(m)/(Math.abs(m)+100) : 100/(m+100); };

function mapGame(g) {
  return {
    id: g.gameId,
    awayTeam: g.awayTeam, homeTeam: g.homeTeam,
    awayPitcher: g.awayPitcher, homePitcher: g.homePitcher,
    gameTime: g.gameTime,
    ml: { away: g.moneyline ? g.moneyline.away : null, home: g.moneyline ? g.moneyline.home : null },
    modelProb: { away: g.modelProb ? g.modelProb.away : null, home: g.modelProb ? g.modelProb.home : null },
    fairProb: { away: g.fairProb ? g.fairProb.away : null, home: g.fairProb ? g.fairProb.home : null },
    edge: g.edge || null,
    spReliable: g.spReliable !== false,
  };
}

function Sparkline({ gameId, height }) {
  const ref = useRef(null);
  const [status, setStatus] = useState('loading');
  const h = height || 48;
  useEffect(() => {
    if (Platform.OS !== 'web') return;
    fetch('https://marketterminal-production.up.railway.app/games/' + gameId + '/history')
      .then(r => r.json())
      .then(data => {
        if (!data || data.length < 2) { setStatus('waiting'); return; }
        setStatus('ok');
        const el = ref.current;
        if (!el) return;
        const w = el.offsetWidth || 280;
        const away = data.map(d => mlToImp(d.away_ml));
        const home = data.map(d => mlToImp(d.home_ml));
        const allVals = [...away, ...home].filter(v => v != null);
        const min = Math.min(...allVals) - 0.005;
        const max = Math.max(...allVals) + 0.005;
        const range = max - min;
        const pt = (vals) => vals.map((v, i) => {
          const x = (i / (vals.length - 1)) * w;
          const y = h - ((v - min) / range) * (h - 10) - 5;
          return [x.toFixed(1), y.toFixed(1)];
        });
        const mkPath = (pts) => pts.map(([x,y],i) => (i===0?'M':'L')+x+' '+y).join(' ');
        const aPts = pt(away);
        const hPts = pt(home);
        const aColor = away[away.length-1] >= away[0] ? '#16a34a' : '#dc2626';
        el.innerHTML = `<svg width="100%" height="${h}" viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" style="display:block"><path d="${mkPath(hPts)}" fill="none" stroke="#3f3f46" stroke-width="1" stroke-dasharray="3,3"/><path d="${mkPath(aPts)}" fill="none" stroke="${aColor}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="${aPts[aPts.length-1][0]}" cy="${aPts[aPts.length-1][1]}" r="2.5" fill="${aColor}"/></svg>`;
      })
      .catch(() => setStatus('error'));
  }, [gameId]);
  if (Platform.OS !== 'web') return null;
  if (status === 'waiting') return (
    <View style={{ height: h, justifyContent:'center', alignItems:'center' }}>
      <Text style={[{ color:'#3f3f46', fontSize:9 }, MONO]}>accumulating line data</Text>
    </View>
  );
  if (status === 'error') return null;
  return <View ref={ref} style={{ height: h, flex:1 }} />;
}

function DivBar({ label, model, fair, edge }) {
  if (model == null) return null;
  const ec = edge == null ? '#52525b' : edge > 0 ? '#16a34a' : '#dc2626';
  const modelW = (model * 100).toFixed(2) + '%';
  const fairW = fair != null ? (fair * 100).toFixed(2) + '%' : null;
  return (
    <View style={s.divRow}>
      <Text style={[s.divLabel, MONO]}>{label}</Text>
      <View style={s.divTrack}>
        {fairW ? <View style={[s.divBarImp, { width: fairW }]} /> : null}
        <View style={[s.divBarModel, { width: modelW, backgroundColor: ec }]} />
      </View>
      <Text style={[s.divPct, MONO, { color: edge == null ? '#52525b' : ec }]}>
        {edge == null ? 'no odds' : fmtEdge(edge)}
      </Text>
    </View>
  );
}

function GameRow({ game }) {
  const [expanded, setExpanded] = useState(false);
  const ae = game.edge ? game.edge.away : null;
  const he = game.edge ? game.edge.home : null;
  const ac = ae == null ? '#52525b' : ae > 0 ? '#16a34a' : '#dc2626';
  const hc = he == null ? '#52525b' : he > 0 ? '#16a34a' : '#dc2626';
  const aFair = game.fairProb ? game.fairProb.away : null;
  const hFair = game.fairProb ? game.fairProb.home : null;
  return (
    <TouchableOpacity onPress={() => setExpanded(!expanded)} activeOpacity={0.7} style={s.card}>
      <View style={s.row}>
        <View style={s.matchup}>
          <View style={{ flexDirection:'row', alignItems:'center', gap:4, marginBottom:3 }}>
            <Text style={[s.ticker, MONO]}>{game.awayTeam}</Text>
            <Text style={[s.at, MONO]}>@</Text>
            <Text style={[s.ticker, MONO]}>{game.homeTeam}</Text>
          </View>
          <Text style={[s.pitcher, MONO]} numberOfLines={1}>{game.awayPitcher} / {game.homePitcher}</Text>
          {!game.spReliable ? <Text style={[s.spWarn, MONO]}>⚠ verify starter</Text> : null}
        </View>
        <View style={s.sepV} />
        <View style={s.mlCol}>
          <Text style={[s.colLbl, MONO]}>AWAY</Text>
          <Text style={[s.mlVal, MONO]}>{fmt(game.ml.away)}</Text>
          <Text style={[s.mlSub, MONO]}>{fmtPct(game.modelProb.away)}</Text>
        </View>
        <View style={s.sepV} />
        <View style={s.mlCol}>
          <Text style={[s.colLbl, MONO]}>HOME</Text>
          <Text style={[s.mlVal, MONO]}>{fmt(game.ml.home)}</Text>
          <Text style={[s.mlSub, MONO]}>{fmtPct(game.modelProb.home)}</Text>
        </View>
        <View style={s.sepV} />
        <View style={s.edgeCol}>
          <Text style={[s.colLbl, MONO]}>EDGE A</Text>
          <Text style={[s.edgeVal, MONO, { color: ac }]}>{fmtEdge(ae)}</Text>
        </View>
        <View style={s.edgeCol}>
          <Text style={[s.colLbl, MONO]}>EDGE H</Text>
          <Text style={[s.edgeVal, MONO, { color: hc }]}>{fmtEdge(he)}</Text>
        </View>
      </View>
      <View style={s.barsWrap}>
        <DivBar label="AWAY" model={game.modelProb.away} fair={aFair} edge={ae} />
        <DivBar label="HOME" model={game.modelProb.home} fair={hFair} edge={he} />
      </View>
      {expanded ? (
        <View style={s.sparkContainer}>
          <View style={s.sparkHeader}>
            <Text style={[s.sparkLbl, MONO]}>LINE MOVEMENT</Text>
            <Text style={[s.sparkLbl, MONO, { color:'#3f3f46' }]}>\u2014 away  - - home</Text>
          </View>
          <Sparkline gameId={game.id} height={48} />
        </View>
      ) : null}
    </TouchableOpacity>
  );
}

export default function FeedScreen() {
  const [games, setGames] = useState([]);
  const [loading, setLoading] = useState(true);
  useEffect(() => {
    fetch('https://marketterminal-production.up.railway.app/games')
      .then(r => r.json())
      .then(data => { setGames(data.map(mapGame)); setLoading(false); })
      .catch(e => { console.error(e); setLoading(false); });
  }, []);
  const today = new Date().toLocaleDateString('en-US', { month:'short', day:'numeric', year:'numeric' });
  return (
    <SafeAreaView style={s.safe}>
      <View style={s.header}>
        <Text style={[s.brand, MONO]}>RAZOR</Text>
        <Text style={[s.headerSub, MONO]}>MLB · {today}</Text>
        <View style={s.badge}><Text style={[s.badgeText, MONO]}>{games.length} MARKETS</Text></View>
      </View>
      <View style={s.th}>
        <Text style={[s.thTxt, MONO, { flex:3 }]}>MATCHUP</Text>
        <Text style={[s.thTxt, MONO, { flex:1.2, textAlign:'center' }]}>AWAY</Text>
        <Text style={[s.thTxt, MONO, { flex:1.2, textAlign:'center' }]}>HOME</Text>
        <Text style={[s.thTxt, MONO, { flex:1.2, textAlign:'center' }]}>EDGE A</Text>
        <Text style={[s.thTxt, MONO, { flex:1.2, textAlign:'center' }]}>EDGE H</Text>
      </View>
      <ScrollView style={{ flex:1 }}>
        {loading ? <Text style={[s.loading, MONO]}>loading markets...</Text> : null}
        {games.map(g => <GameRow key={g.id} game={g} />)}
      </ScrollView>
    </SafeAreaView>
  );
}

const s = StyleSheet.create({
  safe: { flex:1, backgroundColor:'#09090b' },
  header: { flexDirection:'row', alignItems:'center', gap:10, padding:14, paddingBottom:10, borderBottomWidth:1, borderBottomColor:'rgba(255,255,255,0.06)' },
  brand: { color:'|f0eff4', fontSize:15, fontWeight:'700', letterSpacing:3 },
  headerSub: { color:'#52525b', fontSize:11, flex:1 },
  badge: { backgroundColor:'rgba(159,122,234,0.12)', paddingHorizontal:8, paddingVertical:3, borderRadius:4 },
  badgeText: { color:'#9f7aea', fontSize:9, fontWeight:'600', letterSpacing:1.5 },
  th: { flexDirection:'row', paddingHorizontal:14, paddingVertical:7, borderBottomWidth:1, borderBottomColor:'rgba(255,255,255,0.06)' },
  thTxt: { color:'#52525b', fontSize:8, letterSpacing:1.5 },
  card: { borderBottomWidth:1, borderBottomColor:'rgba(255,255,255,0.05)' },
  row: { flexDirection:'row', alignItems:'center', paddingHorizontal:14, paddingVertical:12 },
  matchup: { flex:3 },
  ticker: { color:'#f0eff4', fontSize:13, fontWeight:'600' },
  at: { color:'#52525b', fontSize:10 },
  pitcher: { color:'#52525b', fontSize:9 },
  spWarn: { color:'#d97706', fontSize:8, marginTop:3 },
  sepV: { width:1, height:30, backgroundColor:'rgba(255,255,255,0.06)', marginHorizontal:8 },
  mlCol: { flex:1.2, alignItems:'center' },
  edgeCol: { flex:1.2, alignItems:'center' },
  colLbl: { color:'}52525b', fontSize:8, letterSpacing:1.5, marginBottom:3 },
  mlVal: { color:'#f0eff4', fontSize:13, fontWeight:'600' },
  mlSub: { color:'}52525b', fontSize:8, marginTop:2 },
  edgeVal: { fontSize:12, fontWeight:'600' },
  loading: { color:'#52525b', textAlign:'center', marginTop:40, fontSize:11 },
  barsWrap: { paddingHorizontal:14, paddingBottom:8 },
  divRow: { flexDirection:'row', alignItems:'center', gap:8, marginBottom:4 },
  divLabel: { color:'#52525b', fontSize:8, letterSpacing:1, width:28 },
  divTrack: { flex:1, height:4, backgroundColor:'|27272a', borderRadius:2, position:'relative', overflow:'hidden' },
  divBarImp: { position:'absolute', left:0, top:0, height:4, backgroundColor:'rgba(156,163,175,0.25)', borderRadius:2 },
  divBarModel: { position:'absolute', left:0, top:0, height:4, borderRadius:2 },
  divPct: { fontSize:9, fontWeight:'600', width:46, textAlign:'right' },
  sparkContainer: { paddingHorizontal:14, paddingBottom:12, borderTopWidth:1, borderTopColor:'rgba(255,255,255,0.04)' },
  sparkHeader: { flexDirection:'row', justifyContent:'space-between', marginBottom:8, marginTop:10 },
  sparkLbl: { color:'#52525b', fontSize:8, letterSpacing:1 },
});
