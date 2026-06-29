// state.js — Global application state
const ST={
  streamId:null,
  _es:null,
  locked:false,
  sessionId:'',
  pendingCharts:[],
  pendingPlanSteps:[],
  currentPage:'/chat',
};
let streamEl=null, streamBuf='', streamConf=null;
let _pw=null, _pwBd=null, _pwN=0;
let _upl=false;
let _documentContext=null;      // 最近一次上传的文档（注入消息上下文用）
let _documentContexts=[];       // 全部已上传文档列表（显示用）
let _mentionIdx=-1;
let _profileTable='';
