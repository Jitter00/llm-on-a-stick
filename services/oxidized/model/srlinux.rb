# Nokia SR Linux model for llm-on-a-stick. Oxidized 0.37 ships none (upstream PR ytti/oxidized#2927
# was never merged). SSH exec mode: each command is its own exec request, so no prompt handling.
class SRLinux < Oxidized::Model
  using Refinements

  prompt /[ABCD]:\S+#\s*$/
  comment '# '

  cmd :secret do |cfg|
    cfg.gsub!(/(hashed-password|password) (\S+)/, '\1 <hidden>')
    cfg
  end

  cmd 'info flat'

  cfg :ssh do
    exec true
  end
end
