// state.js — Global application state
const ST={
  streamId:null,
  _es:null,
  locked:false,
  sessionId:'',
  pendingCharts:[],
  pendingPlanSteps:[],
};
let streamEl=null, streamBuf='';
let _pw=null, _pwBd=null, _pwN=0;
let _upl=false;
let _documentContext=null;
