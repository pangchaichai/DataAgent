// state.js — Global application state
const ST={
  streamId:null,
  _es:null,
  locked:false,
  sessionId:'',
  pendingCharts:[],
  pendingPlanSteps:[],
  currentRoute:'/chat',
};
let streamEl=null, streamBuf='', streamConf=null;
let _pw=null, _pwBd=null, _pwN=0;
let _upl=false;
let _documentContext=null;
let _mentionIdx=-1;
let _profileTable='';
