package de.kulanoglu.praxisverwaltung
import android.app.*
import android.os.*
import android.graphics.*
import android.view.*
import android.widget.*
import java.text.SimpleDateFormat
import java.util.*
import android.content.Context
import org.json.JSONObject
import org.json.JSONArray
import java.io.File
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import java.util.Base64

class InkView(ctx: android.content.Context): View(ctx) {
 private val paint=Paint().apply{color=Color.BLACK;strokeWidth=6f;style=Paint.Style.STROKE;strokeCap=Paint.Cap.ROUND;strokeJoin=Paint.Join.ROUND;isAntiAlias=true}
 private val path=Path(); private var eraser=false
 fun setEraser(on:Boolean){eraser=on;paint.color=if(on) Color.WHITE else Color.BLACK;paint.strokeWidth=if(on) 28f else 6f}
 fun setWidth(w:Float){if(!eraser)paint.strokeWidth=w}
 override fun onDraw(c:Canvas){super.onDraw(c);c.drawColor(Color.WHITE);c.drawPath(path,paint)}
 override fun onTouchEvent(e:MotionEvent):Boolean { when(e.action){MotionEvent.ACTION_DOWN->path.moveTo(e.x,e.y);MotionEvent.ACTION_MOVE->path.lineTo(e.x,e.y)};invalidate();return true }
 fun clear(){path.reset();invalidate()}
 fun savePng(file:File){val b=Bitmap.createBitmap(width.coerceAtLeast(1),height.coerceAtLeast(1),Bitmap.Config.ARGB_8888);val c=Canvas(b);draw(c);file.outputStream().use{b.compress(Bitmap.CompressFormat.PNG,100,it)}}
}
class MainActivity: Activity() {
 private fun secretKey():SecretKey{
  val ks=java.security.KeyStore.getInstance("AndroidKeyStore").apply{load(null)}
  val alias="PraxisProLocalKey"
  if(ks.containsAlias(alias)) return (ks.getEntry(alias,null) as java.security.KeyStore.SecretKeyEntry).secretKey
  val kg=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore")
  kg.init(KeyGenParameterSpec.Builder(alias,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
  return kg.generateKey()
 }
 private fun encryptString(value:String):String{
  val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,secretKey())
  return Base64.getEncoder().encodeToString(cipher.iv)+"."+Base64.getEncoder().encodeToString(cipher.doFinal(value.toByteArray(Charsets.UTF_8)))
 }
 private fun decryptString(value:String):String=try{
  val p=value.split(".");val cipher=Cipher.getInstance("AES/GCM/NoPadding");val spec=javax.crypto.spec.GCMParameterSpec(128,Base64.getDecoder().decode(p[0]));cipher.init(Cipher.DECRYPT_MODE,secretKey(),spec);String(cipher.doFinal(Base64.getDecoder().decode(p[1])),Charsets.UTF_8)
 }catch(e:Exception){value}
 private fun secureWrite(file:File,text:String){file.writeText(encryptString(text))}
 private fun secureRead(file:File):String=if(file.exists()) decryptString(file.readText()) else ""

 private fun clientFile()=File(filesDir,"clients.json")
 private fun loadClients():JSONArray=try{JSONArray(secureRead(clientFile()))}catch(e:Exception){JSONArray()}
 private fun rememberClient(last:String,first:String){
  if(last.isBlank()&&first.isBlank())return
  val a=loadClients(); for(i in 0 until a.length()){val o=a.getJSONObject(i);if(o.optString("last")==last&&o.optString("first")==first)return}
  a.put(JSONObject().put("last",last).put("first",first));secureWrite(clientFile(),a.toString(2))
 }
 private fun showClients(last:EditText,first:EditText){
  val a=loadClients();val labels=ArrayList<String>();for(i in 0 until a.length()){val o=a.getJSONObject(i);labels.add(o.optString("last")+", "+o.optString("first"))}
  AlertDialog.Builder(this).setTitle("Klienten").setItems(labels.toTypedArray()){_,i->val o=a.getJSONObject(i);last.setText(o.optString("last"));first.setText(o.optString("first"))}.setNegativeButton("Schließen",null).show()
 }
 private fun showHistory(last:String,first:String){
  val dir=File(filesDir,"sessions");val files=dir.listFiles{f->f.name.startsWith("session_")&&(f.extension=="json"||f.extension=="enc")}?.sortedByDescending{it.lastModified()}?: emptyList()
  val rows=ArrayList<Pair<String,String>>()
  for(f in files)try{val o=JSONObject(secureRead(f));if(o.optString("last")==last&&o.optString("first")==first){
    rows.add(Pair(o.optString("date")+"   "+o.optString("begin")+"–"+o.optString("end"),o.optString("notes")))
  }}catch(_:Exception){}
  if(rows.isEmpty()){Toast.makeText(this,"Keine gespeicherten Sitzungen",Toast.LENGTH_SHORT).show();return}
  AlertDialog.Builder(this).setTitle("Sitzungsverlauf – $first $last").setItems(rows.map{it.first}.toTypedArray()){_,i->
    AlertDialog.Builder(this).setTitle(rows[i].first).setMessage(rows[i].second.ifBlank{"Keine Textnotiz"}).setPositiveButton("Schließen",null).show()
  }.setNegativeButton("Schließen",null).show()
 }
 private lateinit var clock:TextView; private lateinit var timer:TextView; private var startMs=0L; private var elapsed=0L; private var running=false
 private val h=Handler(Looper.getMainLooper())
 private val tick=object:Runnable{override fun run(){
  clock.text="LIVE  "+SimpleDateFormat("HH:mm:ss",Locale.GERMANY).format(Date())
  val ms=elapsed + if(running) System.currentTimeMillis()-startMs else 0L; val sec=ms/1000
  timer.text=String.format(Locale.GERMANY,"%02d:%02d:%02d",sec/3600,(sec%3600)/60,sec%60); h.postDelayed(this,250)}}
 override fun onCreate(b:Bundle?){super.onCreate(b)
  val root=LinearLayout(this).apply{orientation=LinearLayout.VERTICAL;setPadding(24,24,24,24)}
  val title=TextView(this).apply{text="Praxisverwaltung";textSize=26f;setTypeface(null,1)}
  clock=TextView(this).apply{textSize=24f;gravity=Gravity.END}
  timer=TextView(this).apply{textSize=30f;gravity=Gravity.CENTER;text="00:00:00"}
  root.addView(title);root.addView(clock);root.addView(timer)
  val names=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL}
  val last=EditText(this).apply{hint="Nachname"}; val first=EditText(this).apply{hint="Vorname"}
  names.addView(last,LinearLayout.LayoutParams(0,-2,1f));names.addView(first,LinearLayout.LayoutParams(0,-2,1f));root.addView(names)
  val clientActions=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL}
  val activity=this
  val choose=Button(this).apply{text="Klient auswählen";setOnClickListener{activity.showClients(last,first)}}
  val history=Button(this).apply{text="Sitzungsverlauf";setOnClickListener{
    if(last.text.isBlank()&&first.text.isBlank()) Toast.makeText(activity,"Bitte zuerst Klient auswählen",Toast.LENGTH_SHORT).show()
    else activity.showHistory(last.text.toString().trim(),first.text.toString().trim())
  }}
  clientActions.addView(choose,LinearLayout.LayoutParams(0,-2,1f));clientActions.addView(history,LinearLayout.LayoutParams(0,-2,1f));root.addView(clientActions)
  val date=EditText(this).apply{hint="Datum";setText(SimpleDateFormat("dd.MM.yyyy",Locale.GERMANY).format(Date()))}
  val begin=EditText(this).apply{hint="Beginn (manuell)"}; val end=EditText(this).apply{hint="Ende"}
  root.addView(date);root.addView(begin);root.addView(end)
  val note=EditText(this).apply{hint="Sitzungsnotiz";gravity=Gravity.TOP;minLines=4};root.addView(note)
  val ink=InkView(this);root.addView(ink,LinearLayout.LayoutParams(-1,0,1f))
  val buttons=LinearLayout(this).apply{orientation=LinearLayout.HORIZONTAL}
  val start=Button(this).apply{text="Start";setOnClickListener{if(!running){startMs=System.currentTimeMillis();running=true}}}
  val pause=Button(this).apply{text="Pause";setOnClickListener{if(running){elapsed+=System.currentTimeMillis()-startMs;running=false}else{startMs=System.currentTimeMillis();running=true}}}
  val stop=Button(this).apply{text="Ende";setOnClickListener{if(running)elapsed+=System.currentTimeMillis()-startMs;running=false;end.setText(SimpleDateFormat("HH:mm",Locale.GERMANY).format(Date()))}}
  val eraser=ToggleButton(this).apply{textOn="Radierer AN";textOff="Radierer";setOnCheckedChangeListener{_,on->ink.setEraser(on)}}
  val clear=Button(this).apply{text="Stift löschen";setOnClickListener{ink.clear()}}
  buttons.addView(start);buttons.addView(pause);buttons.addView(stop);buttons.addView(eraser);buttons.addView(clear);root.addView(buttons)
  val save=Button(this).apply{text="Sitzung lokal speichern";setOnClickListener{
    val o=JSONObject();o.put("last",last.text.toString());o.put("first",first.text.toString());o.put("date",date.text.toString());o.put("begin",begin.text.toString());o.put("end",end.text.toString());o.put("seconds",elapsed/1000);o.put("notes",note.text.toString())
    rememberClient(last.text.toString().trim(),first.text.toString().trim())
    val dir=File(filesDir,"sessions");dir.mkdirs();val stamp=System.currentTimeMillis();val inkFile=File(dir,"handwriting_"+stamp+".png");ink.savePng(inkFile);o.put("ink_file",inkFile.absolutePath);secureWrite(File(dir,"session_"+stamp+".json.enc"),o.toString(2))
    Toast.makeText(activity,"Sitzung + Handschrift lokal gespeichert",Toast.LENGTH_SHORT).show()
  }};root.addView(save)
  setContentView(root);h.post(tick)
 }
 override fun onDestroy(){h.removeCallbacks(tick);super.onDestroy()}
}
